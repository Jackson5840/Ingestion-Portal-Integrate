import mysql.connector
import numpy as np
import pandas as pd
from flask import Flask, send_from_directory, jsonify, request
from flask_cors import CORS, cross_origin
import ast, json, re, requests, os
from copy import deepcopy
import datetime
import redis
import time
import logging
import subprocess
import tempfile
import shutil
import ipaddress
import uuid
from collections import defaultdict
from threading import Thread
from are import cfg,io,com,utils,ingest,ingestdiameter,datagen
#from IngestApp import Ingestion


app = Flask(__name__)
app.debug = True
CORS(app)
r = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', '6379')),
    db=int(os.getenv('REDIS_DB', '0')),
)
logging.basicConfig(level=logging.INFO,filename='app.log', filemode='w', format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s')


def _job_key(job_type, archive, suffix):
    return "{}_{}_{}".format(archive, job_type, suffix)


def _decode_redis(value, default=''):
    if isinstance(value, bytes):
        return value.decode()
    if value is None:
        return default
    return value


def normalize_server_path(path_value):
    path_value = (path_value or '').strip().strip('"').strip("'")
    m = re.match(r'^\\\\wsl\.localhost\\[^\\]+\\(.*)', path_value)
    if m:
        return '/' + m.group(1).replace('\\', '/')
    m = re.match(r'^([A-Za-z]):[\\\/](.*)', path_value)
    if m:
        return '/mnt/' + m.group(1).lower() + '/' + m.group(2).replace('\\', '/')
    return path_value


def _set_archive_job(job_type, archive, current=None, total=None, message=None, status=None):
    if current is not None:
        r.set(_job_key(job_type, archive, 'current'), int(current))
    if total is not None:
        r.set(_job_key(job_type, archive, 'total'), int(total))
    if current is not None or total is not None:
        stored_current = current
        stored_total = total
        if stored_current is None:
            stored_current = r.get(_job_key(job_type, archive, 'current')) or 0
        if stored_total is None:
            stored_total = r.get(_job_key(job_type, archive, 'total')) or 0
        stored_current = int(stored_current)
        stored_total = int(stored_total)
        progress = (stored_current / stored_total * 100) if stored_total else 0
        r.set(_job_key(job_type, archive, 'progress'), max(0, min(100, progress)))
    if message is not None:
        r.set(_job_key(job_type, archive, 'message'), message)
        r.rpush(_job_key(job_type, archive, 'log'), message)
        r.ltrim(_job_key(job_type, archive, 'log'), -100, -1)
    if status is not None:
        r.set(_job_key(job_type, archive, 'status'), status)


def _get_archive_job(job_type, archive):
    log_lines = r.lrange(_job_key(job_type, archive, 'log'), -100, -1)
    progress = r.get(_job_key(job_type, archive, 'progress'))
    current = r.get(_job_key(job_type, archive, 'current'))
    total = r.get(_job_key(job_type, archive, 'total'))
    return {
        'status': _decode_redis(r.get(_job_key(job_type, archive, 'status')), 'idle'),
        'progress': float(progress) if progress is not None else 0,
        'current': int(current) if current else 0,
        'total': int(total) if total else 0,
        'message': _decode_redis(r.get(_job_key(job_type, archive, 'message')), ''),
        'log': [_decode_redis(item) for item in log_lines],
    }


def _archive_job_is_running(job_type, archive):
    return _get_archive_job(job_type, archive)['status'] in ('running', 'stopping')


def _prepare_archive_job(job_type, archive, message):
    r.delete(_job_key(job_type, archive, 'stop'))
    r.delete(_job_key(job_type, archive, 'log'))
    _set_archive_job(job_type, archive, current=0, total=0, message=message, status='running')


def _archive_job_should_stop(job_type, archive):
    return bool(r.get(_job_key(job_type, archive, 'stop')))


def _workflow_lock_value(job_type, archive):
    return '{}:{}'.format(job_type, archive)


def _claim_archive_workflow_lock(job_type, archive):
    desired = _workflow_lock_value(job_type, archive)
    owner = _decode_redis(r.get('archive_workflow_lock'), '')
    if owner:
        parts = owner.split(':', 1)
        if len(parts) == 2 and _archive_job_is_running(parts[0], parts[1]):
            return False, owner
    r.set('archive_workflow_lock', desired, ex=7 * 24 * 60 * 60)
    return True, desired


def _release_archive_workflow_lock(job_type, archive):
    desired = _workflow_lock_value(job_type, archive)
    owner = _decode_redis(r.get('archive_workflow_lock'), '')
    if owner == desired:
        r.delete('archive_workflow_lock')


def _parse_ingest_threads(value):
    try:
        threads = int(value)
    except (TypeError, ValueError):
        return 1
    if threads >= 8:
        return 8
    if threads >= 4:
        return 4
    if threads >= 2:
        return 2
    return 1


def _run_ingest_archive_job(folder_name, threads=1):
    job_type = 'ingest'
    def progress_cb(current, total, message, status='running'):
        _set_archive_job(job_type, folder_name, current=current, total=total, message=message, status=status)

    try:
        cfg.sshdir = cfg.sshreviewdir
        progress_cb(0, 0, 'Starting ingest for {} with {} thread(s)'.format(folder_name, threads))
        neuron_results = ingest.ingestarchive(
            folder_name,
            progress_cb=progress_cb,
            should_stop=lambda: _archive_job_should_stop(job_type, folder_name),
            threads=threads,
        )
        errors = [item for item in neuron_results if neuron_results[item].get('status') == 'error']
        current_state = _get_archive_job(job_type, folder_name)
        if _archive_job_should_stop(job_type, folder_name) or current_state['status'] == 'stopped':
            _set_archive_job(job_type, folder_name, message='Ingest stopped for {}'.format(folder_name), status='stopped')
        elif errors:
            _set_archive_job(job_type, folder_name, message='Ingest finished with {} error(s)'.format(len(errors)), status='error')
        else:
            _set_archive_job(job_type, folder_name, current=current_state['total'], total=current_state['total'], message='Ingest complete for {}'.format(folder_name), status='success')
    except Exception:
        logging.exception("Error during background ingest of archive {}".format(folder_name))
        _set_archive_job(job_type, folder_name, message='Ingest failed for {}'.format(folder_name), status='error')
    finally:
        com.close_workflow_sessions()
        _release_archive_workflow_lock(job_type, folder_name)


def _run_read_archive_job(archive, steps=None):
    job_type = 'read'
    def progress_cb(current, total, message, status='running'):
        _set_archive_job(job_type, archive, current=current, total=total, message=message, status=status)

    try:
        progress_cb(0, 100, 'Starting Read Archive for {}'.format(archive))
        result = io.getfiles(
            archive,
            steps or {},
            progress_cb=progress_cb,
            should_stop=lambda: _archive_job_should_stop(job_type, archive),
        )
        if result.get('status') == 'stopped' or _archive_job_should_stop(job_type, archive):
            _set_archive_job(job_type, archive, message='Read Archive stopped for {}'.format(archive), status='stopped')
        elif result.get('status') == 'error':
            _set_archive_job(job_type, archive, message=result.get('message', 'Read Archive failed for {}'.format(archive)), status='error')
        else:
            _set_archive_job(job_type, archive, current=100, total=100, message=result.get('message', 'Read Archive complete for {}'.format(archive)), status='success')
    except Exception:
        logging.exception("Error during background read of archive {}".format(archive))
        _set_archive_job(job_type, archive, message='Read Archive failed for {}'.format(archive), status='error')
    finally:
        _release_archive_workflow_lock(job_type, archive)


def _run_export_to_main_job(archive, threads=1):
    job_type = 'exportmain'
    def progress_cb(current, total, message, status='running'):
        _set_archive_job(job_type, archive, current=current, total=total, message=message, status=status)

    try:
        now = datetime.datetime.now()
        dt_string = now.strftime("%Y-%m-%d")
        cfg.sshdir = cfg.sshreviewdir
        cfg.dbsel = cfg.dbselmain
        progress_cb(0, 100, 'Starting Export to main for {} with {} thread(s)'.format(archive, threads))
        release_result = io.mainrelease(
            archive,
            dt_string,
            progress_cb=progress_cb,
            should_stop=lambda: _archive_job_should_stop(job_type, archive),
            threads=threads,
        )
        if release_result.get('status') == 'stopped' or _archive_job_should_stop(job_type, archive):
            _set_archive_job(job_type, archive, message='Export to main stopped for {}'.format(archive), status='stopped')
            return
        cfg.sshdir = cfg.sshmaindir
        progress_cb(96, 100, 'Generating WIN.jsp and release info')
        (version,nneurons) = io.genwinjsp(archive, dt_string)
        io.writeendings(archive)
        io.updateinfo(archive,version,dt_string)
        # Temporarily disable the main publish workflow trigger.
        # io.mainworkflow()
        io.updatetickertape()
        progress_cb(100, 100, 'Export to main complete for {}'.format(archive), 'success')
    except Exception:
        logging.exception("Error during background export to main site of archive {}".format(archive))
        _set_archive_job(job_type, archive, message='Export to main failed for {}'.format(archive), status='error')
    finally:
        com.close_workflow_sessions()
        cfg.sshdir = cfg.sshreviewdir
        cfg.dbsel = cfg.dbselrev
        _release_archive_workflow_lock(job_type, archive)


def _run_datagen_job(job_id, generator_type, xlsx_path, outputdir, upload_root, database):
    job_type = 'datagen'

    def progress_cb(current, total, message, status='running'):
        _set_archive_job(job_type, job_id, current=current, total=total, message=message, status=status)

    try:
        progress_cb(0, 0, 'Reading xlsx for {}'.format(generator_type))
        if generator_type == 'MeasurementGEN':
            result = datagen.generate_measurements(xlsx_path, outputdir, progress_cb=progress_cb, database=database)
        elif generator_type == 'MetadataGEN':
            result = datagen.generate_metadata(xlsx_path, outputdir, progress_cb=progress_cb, database=database)
        else:
            raise ValueError('Invalid DataGEN type: {}'.format(generator_type))
        status = 'success' if result.get('status') == 'success' else 'warning'
        current_state = _get_archive_job(job_type, job_id)
        _set_archive_job(
            job_type,
            job_id,
            current=current_state['total'],
            total=current_state['total'],
            message='{} complete: generated {}, missing {}, failed {}. Output: {}'.format(
                generator_type,
                result.get('generated', 0),
                result.get('missing', 0),
                result.get('failed', 0),
                '{} ({})'.format(outputdir, database),
            ),
            status=status,
        )
        r.set(_job_key(job_type, job_id, 'result'), json.dumps(result))
    except Exception as exc:
        logging.exception('DataGEN job failed: %s', job_id)
        _set_archive_job(job_type, job_id, message='{} failed: {}'.format(generator_type, exc), status='error')
    finally:
        shutil.rmtree(upload_root, ignore_errors=True)


@app.route('/', methods=['GET'])
def get():
    return "Ingestion app is up!"

# Serve the UI index page
@app.route('/ui/')
def serve_ui_index():
    return send_from_directory(os.path.join(app.root_path, 'ui'), 'index.html')

# Serve UI static files (CSS, JS, images, etc.)
@app.route('/ui/<path:filename>')
def serve_ui_static(filename):
    return send_from_directory(os.path.join(app.root_path, 'ui'), filename)

@app.route('/diametercheck/<string:folder_name>',  methods=['GET'])
def diametercheck(folder_name):
    cfg.sshdir = cfg.sshreviewdir
    neuronResults = ingestdiameter.ingestarchive(folder_name)

    if any([neuronResults[item]['status'] == 'error' for item in neuronResults]):
        return {
            'data': ', '.join(['{}: {}'.format(item,neuronResults[item]['message']) for item in neuronResults if neuronResults[item]['status'] == 'error']),
            'status': 'error'
        }
    else:
        return {
            'data': 'Archive {} ingested'.format(folder_name),
            'status': 'success'
        }

@app.route('/checkgif/<string:archive>', methods=['GET'])
def checkgif(archive):
    
    status = r.get("{}_gif_status".format(archive))
    progress = r.get("{}_gif_progress".format(archive))
    current = r.get("{}_gif_current".format(archive))
    total = r.get("{}_gif_total".format(archive))
    message = r.get("{}_gif_message".format(archive))
    log_lines = r.lrange("{}_gif_log".format(archive), -80, -1)

    if progress is None:
        progress = 0
    else:
        progress = float(progress)
    result = {
        'status': status.decode() if isinstance(status, bytes) else (status or 'idle'),
        'progress': progress,
        'current': int(current) if current else 0,
        'total': int(total) if total else 0,
        'message': message.decode() if isinstance(message, bytes) else (message or ''),
        'log': [
            item.decode() if isinstance(item, bytes) else str(item)
            for item in log_lines
        ]
    }
    logging.info("Result = {}".format(result))
    return result

@app.route('/stopgif/<string:archive>', methods=['POST'])
def stopgif(archive):
    r.set("{}_gif_stop".format(archive), '1')
    r.set("{}_gif_status".format(archive), 'stopping')
    r.set("{}_gif_message".format(archive), 'Stop requested. Finishing current work before stopping.')
    r.rpush("{}_gif_log".format(archive), 'Stop requested. Finishing current work before stopping.')
    r.ltrim("{}_gif_log".format(archive), -80, -1)
    return {'status': 'stopping', 'job_id': archive}

@app.route('/checkpvec/<string:job_id>', methods=['GET'])
def checkpvec(job_id):
    status = r.get("{}_pvec_status".format(job_id))
    progress = r.get("{}_pvec_progress".format(job_id))
    current = r.get("{}_pvec_current".format(job_id))
    total = r.get("{}_pvec_total".format(job_id))
    message = r.get("{}_pvec_message".format(job_id))

    result = {
        'status': status.decode() if isinstance(status, bytes) else (status or 'idle'),
        'progress': float(progress) if progress is not None else 0,
        'current': int(current) if current else 0,
        'total': int(total) if total else 0,
        'message': message.decode() if isinstance(message, bytes) else (message or '')
    }
    logging.info("Result = {}".format(result))
    return result

@app.route('/setstatus/', methods=['POST'])
def setstatus():
    payloadData = request.get_json()
    neuron_name = payloadData['archive']
    toset = payloadData['status']
    r.set(archive,toset)
    return 'status set'

@app.route('/getarchives/', methods=['GET'])
def getarchives():
    result = io.getarchivecsv()
    return result


@app.route('/logs/are', methods=['GET'])
def get_are_logs():
    lines = int(request.args.get('lines', '200'))
    lines = max(10, min(lines, 1000))
    logfile = os.path.join(app.root_path, 'app.log')
    if not os.path.exists(logfile):
        return {'status': 'success', 'content': '', 'lines': 0}

    with open(logfile, 'r', encoding='utf-8', errors='replace') as handle:
        content_lines = handle.readlines()

    filtered_lines = [
        line for line in content_lines
        if 'GET /logs/are?lines=' not in line
    ]
    tail = filtered_lines[-lines:]
    return {
        'status': 'success',
        'content': ''.join(tail),
        'lines': len(tail),
    }


@app.route('/exportdb/', methods=['GET'])
def exportdb():
    export_root = os.getenv('ARE_EXPORT_ROOT', '/home/kira/app/Ingestion/export')
    os.makedirs(export_root, exist_ok=True)
    selected = request.args.getlist('db')
    if not selected:
        selected = ['mysql_review', 'mysql_main', 'postgres']

    today = datetime.datetime.now().strftime('%Y-%m-%d')
    outputs = {}
    mysql_dump_user = os.getenv('ARE_MYSQL_DUMP_USER', 'root')
    mysql_dump_password = os.getenv('ARE_MYSQL_ROOT_PASSWORD', os.getenv('ARE_MYSQL_PASSWORD', ''))

    try:
        if 'mysql_review' in selected:
            mysql_review_output = os.path.join(export_root, 'mysql_{}_{}.sql'.format(cfg.dbselrev, today))
            mysql_cmd = [
                'mysqldump',
                '--host', cfg.dbhost,
                '--user', mysql_dump_user,
                '--single-transaction',
                '--column-statistics=0',
                '--no-tablespaces',
                '--routines',
                '--events',
                '--triggers',
                '--set-gtid-purged=OFF',
                cfg.dbselrev,
            ]
            mysql_env = os.environ.copy()
            mysql_env['MYSQL_PWD'] = mysql_dump_password
            with open(mysql_review_output, 'w', encoding='utf-8') as handle:
                subprocess.run(
                    mysql_cmd,
                    check=True,
                    stdout=handle,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    env=mysql_env,
                )
            outputs['mysql_review'] = mysql_review_output

        if 'mysql_main' in selected:
            mysql_main_output = os.path.join(export_root, 'mysql_{}_{}.sql'.format(cfg.dbselmain, today))
            mysql_cmd = [
                'mysqldump',
                '--host', cfg.dbhost,
                '--user', mysql_dump_user,
                '--single-transaction',
                '--column-statistics=0',
                '--no-tablespaces',
                '--routines',
                '--events',
                '--triggers',
                '--set-gtid-purged=OFF',
                cfg.dbselmain,
            ]
            mysql_env = os.environ.copy()
            mysql_env['MYSQL_PWD'] = mysql_dump_password
            with open(mysql_main_output, 'w', encoding='utf-8') as handle:
                subprocess.run(
                    mysql_cmd,
                    check=True,
                    stdout=handle,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    env=mysql_env,
                )
            outputs['mysql_main'] = mysql_main_output

        if 'postgres' in selected:
            postgres_output = os.path.join(export_root, 'postgres_{}_{}.sql'.format(cfg.pg_database, today))
            postgres_cmd = [
                'pg_dump',
                '--host', cfg.pg_host,
                '--port', str(cfg.pg_port),
                '--username', cfg.pg_user,
                '--dbname', cfg.pg_database,
                '--format', 'plain',
                '--clean',
                '--if-exists',
            ]
            postgres_env = os.environ.copy()
            postgres_env['PGPASSWORD'] = cfg.pg_password
            with open(postgres_output, 'w', encoding='utf-8') as handle:
                subprocess.run(
                    postgres_cmd,
                    check=True,
                    stdout=handle,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    env=postgres_env,
                )
            outputs['postgres'] = postgres_output

        return {
            'status': 'success',
            'outputs': outputs,
        }
    except subprocess.CalledProcessError as exc:
        logging.exception("Database export failed")
        return {
            'status': 'error',
            'message': (exc.stderr or str(exc)).strip(),
        }, 500


@app.route('/importdb/', methods=['POST'])
def importdb():
    db_target = request.form.get('db_target', '').strip()
    dump_file = request.files.get('dump_file')
    export_root = os.getenv('ARE_EXPORT_ROOT', '/home/kira/app/Ingestion/export')
    os.makedirs(export_root, exist_ok=True)

    if db_target not in {'mysql_review', 'mysql_main', 'logging_data', 'postgres'}:
        return {'status': 'error', 'message': 'Invalid database target.'}, 400
    if dump_file is None or not dump_file.filename:
        return {'status': 'error', 'message': 'No dump file uploaded.'}, 400

    temp_path = None
    try:
        suffix = os.path.splitext(dump_file.filename)[1] or '.sql'
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=export_root) as tmp:
            dump_file.save(tmp)
            temp_path = tmp.name

        if db_target in {'mysql_review', 'mysql_main', 'logging_data'}:
            mysql_import_user = os.getenv('ARE_MYSQL_DUMP_USER', 'root')
            mysql_import_password = os.getenv('ARE_MYSQL_ROOT_PASSWORD', os.getenv('ARE_MYSQL_PASSWORD', ''))
            if db_target == 'mysql_review':
                mysql_database = cfg.dbselrev
            elif db_target == 'mysql_main':
                mysql_database = cfg.dbselmain
            else:
                mysql_database = os.getenv('ARE_MYSQL_LOGGING_DB', 'LoggingData')

            if db_target == 'logging_data':
                mysql_create_cmd = [
                    'mysql',
                    '--host', cfg.dbhost,
                    '--user', mysql_import_user,
                    '-e',
                    "CREATE DATABASE IF NOT EXISTS `{}` DEFAULT CHARACTER SET latin1".format(mysql_database),
                ]
                mysql_env = os.environ.copy()
                mysql_env['MYSQL_PWD'] = mysql_import_password
                subprocess.run(
                    mysql_create_cmd,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    env=mysql_env,
                )

            mysql_cmd = [
                'mysql',
                '--host', cfg.dbhost,
                '--user', mysql_import_user,
                mysql_database,
            ]
            mysql_env = os.environ.copy()
            mysql_env['MYSQL_PWD'] = mysql_import_password
            with open(temp_path, 'r', encoding='utf-8', errors='replace') as handle:
                subprocess.run(
                    mysql_cmd,
                    check=True,
                    stdin=handle,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    env=mysql_env,
                )
            imported_db = mysql_database
        else:
            postgres_cmd = [
                'psql',
                '--host', cfg.pg_host,
                '--port', str(cfg.pg_port),
                '--username', cfg.pg_user,
                '--dbname', cfg.pg_database,
                '--file', temp_path,
            ]
            postgres_env = os.environ.copy()
            postgres_env['PGPASSWORD'] = cfg.pg_password
            subprocess.run(
                postgres_cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                env=postgres_env,
            )
            imported_db = cfg.pg_database

        return {
            'status': 'success',
            'database': imported_db,
            'filename': dump_file.filename,
        }
    except subprocess.CalledProcessError as exc:
        logging.exception("Database import failed")
        return {
            'status': 'error',
            'message': (exc.stderr or exc.stdout or str(exc)).strip(),
        }, 500
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@app.route('/exportarchivedata/<string:archive>', methods=['GET'])
def exportarchivedata(archive):
    archive_export_root = os.getenv('ARE_ARCHIVE_EXPORT_ROOT', '/home/kira/app/Ingestion/dataexport')
    bundle_root = os.path.join(archive_export_root, archive)
    files_root = os.path.join(bundle_root, 'files')
    jsp_root = os.path.join(bundle_root, 'jsp')
    xml_root = os.path.join(bundle_root, 'xml')

    def ensure_parent(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def copy_file(src, dest):
        ensure_parent(dest)
        shutil.copy2(src, dest)

    def copy_tree(src, dest):
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.copytree(src, dest)

    try:
        archive_status = io.getarchivecsv()
        matching = [item for item in archive_status.get('data', []) if item.get('name') == archive]
        if not matching:
            return {'status': 'error', 'message': 'Archive not found.'}, 404
        if matching[0].get('status') not in ('public', 'published'):
            return {'status': 'error', 'message': 'Archive has not completed Export to main.'}, 400

        if os.path.exists(bundle_root):
            shutil.rmtree(bundle_root)
        os.makedirs(files_root, exist_ok=True)
        os.makedirs(jsp_root, exist_ok=True)
        os.makedirs(xml_root, exist_ok=True)

        archive_lower = archive.lower()
        main_root = cfg.sshmaindir

        data_dirs = [
            (
                os.path.join(main_root, 'dableFiles', archive_lower),
                os.path.join(files_root, 'dableFiles', archive_lower),
            ),
            (
                os.path.join(main_root, 'images', 'imageFiles', archive),
                os.path.join(files_root, 'images', 'imageFiles', archive),
            ),
        ]

        for src, dest in data_dirs:
            if os.path.exists(src):
                copy_tree(src, dest)

        neuron_names, _ = com.getarchiveneurons(archive)
        rotating_src = os.path.join(main_root, 'rotatingImages')
        rotating_dest = os.path.join(files_root, 'rotatingImages')
        os.makedirs(rotating_dest, exist_ok=True)
        for neuron_name in neuron_names:
            gif_name = neuron_name + '.CNG.gif'
            gif_src = os.path.join(rotating_src, gif_name)
            if os.path.exists(gif_src):
                copy_file(gif_src, os.path.join(rotating_dest, gif_name))

        scrolling_src = os.path.join(main_root, 'images', 'scrollingText')
        scrolling_dest = os.path.join(files_root, 'images', 'scrollingText')
        if os.path.exists(scrolling_src):
            copy_tree(scrolling_src, scrolling_dest)

        jsp_files = ['WIN.jsp', 'Header.jsp', 'index.jsp']
        for filename in jsp_files:
            src = os.path.join(main_root, filename)
            if os.path.exists(src):
                copy_file(src, os.path.join(jsp_root, filename))

        xml_files = ['archive_swc.xml', 'archive_all.xml']
        for filename in xml_files:
            src = os.path.join(main_root, 'xml', filename)
            if os.path.exists(src):
                copy_file(src, os.path.join(xml_root, filename))

        return {
            'status': 'success',
            'bundle_root': bundle_root,
        }
    except Exception as exc:
        logging.exception("Archive data export failed")
        return {
            'status': 'error',
            'message': str(exc),
        }, 500

@app.route('/gifgen/<string:archive>', methods=['GET'])
def gifgen(archive):
    try:
        result = io.genarchivegifs(archive)
        logging.info("Result = {}".format(result))

    except Exception as identifier:
        pass

    return result

@app.route('/upload_swc_folder', methods=['POST'])
def upload_swc_folder():
    folder_name = request.form.get('folder_name', 'selected_swc_folder')
    safe_folder_name = ''.join([c if c.isalnum() or c in ('-', '_', '.') else '_' for c in folder_name]) or 'selected_swc_folder'
    upload_root = os.path.join(tempfile.gettempdir(), 'are_uploaded_swc')
    os.makedirs(upload_root, exist_ok=True)
    upload_dir = tempfile.mkdtemp(prefix=safe_folder_name + '_', dir=upload_root)

    files = request.files.getlist('files')
    saved = 0
    for uploaded in files:
        filename = os.path.basename(uploaded.filename.replace('\\', '/'))
        if not filename.lower().endswith('.swc'):
            continue
        uploaded.save(os.path.join(upload_dir, filename))
        saved += 1

    if saved == 0:
        shutil.rmtree(upload_dir, ignore_errors=True)
        return {'status': 'error', 'message': 'No .swc files found in selected folder'}

    return {'status': 'success', 'swcdir': upload_dir, 'count': saved}


LOG_TIME_FORMAT = '%d/%b/%Y:%H:%M:%S %z'
ACCESS_LOG_RE = re.compile(
    r'^(?P<ip>\S+)\s+\S+\s+\S+\s+\[(?P<time>[^\]]+)\]\s+"[^"]*"\s+(?P<status>\d{3})\s+'
)
HIT_LOG_QUARTER_RE = re.compile(r'^(?P<year>\d{4})\s*Q(?P<quarter>[1-4])$')


def is_localhost_ip(ip_text):
    value = (ip_text or '').strip().lower()
    if value in {'localhost', '0:0:0:0:0:0:0:1'}:
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def parse_access_log_line(line):
    match = ACCESS_LOG_RE.match(line)
    if match is None:
        return None
    ip_text = match.group('ip')
    if is_localhost_ip(ip_text):
        return None
    if match.group('status') != '200':
        return None
    try:
        accessed_at = datetime.datetime.strptime(match.group('time'), LOG_TIME_FORMAT)
    except ValueError:
        return None
    quarter = ((accessed_at.month - 1) // 3) + 1
    return ip_text, '{} Q{}'.format(accessed_at.year, quarter)


def lookup_countries_for_ips(ip_texts):
    country_by_ip = {}
    candidates = []
    for ip_text in sorted(set(ip_texts)):
        try:
            parsed = ipaddress.ip_address(ip_text)
            if parsed.is_private or parsed.is_loopback or parsed.is_multicast or parsed.is_unspecified:
                country_by_ip[ip_text] = 'Unknown IP'
                continue
        except ValueError:
            country_by_ip[ip_text] = 'Unknown IP'
            continue
        candidates.append(ip_text)

    lookup_mode = os.getenv('ARE_HIT_LOG_COUNTRY_LOOKUP', 'online').lower()
    if lookup_mode != 'online':
        for ip_text in candidates:
            country_by_ip[ip_text] = 'Unknown IP'
        return country_by_ip

    for index in range(0, len(candidates), 100):
        chunk = candidates[index:index + 100]
        try:
            response = requests.post(
                'http://ip-api.com/batch?fields=status,country,query',
                json=chunk,
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            for item in payload:
                ip_text = item.get('query')
                country = item.get('country') if item.get('status') == 'success' else None
                if ip_text:
                    country_by_ip[ip_text] = country or 'Unknown IP'
        except Exception:
            logging.exception('Country lookup failed for hit log chunk')
            for ip_text in chunk:
                country_by_ip[ip_text] = 'Unknown IP'

    for ip_text in candidates:
        country_by_ip.setdefault(ip_text, 'Unknown IP')
    return country_by_ip


def analyze_hit_log_files(files):
    per_quarter = defaultdict(int)
    ip_hits = defaultdict(int)
    files_processed = 0
    lines_read = 0
    lines_counted = 0

    for path in files:
        files_processed += 1
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            for line in handle:
                lines_read += 1
                parsed = parse_access_log_line(line)
                if parsed is None:
                    continue
                ip_text, quarter = parsed
                lines_counted += 1
                per_quarter[(quarter, ip_text)] += 1
                ip_hits[ip_text] += 1

    country_by_ip = lookup_countries_for_ips(ip_hits.keys())
    country_hits = defaultdict(int)
    country_ips = defaultdict(set)
    for ip_text, hits in ip_hits.items():
        country = country_by_ip.get(ip_text, 'Unknown IP')
        country_hits[country] += hits
        country_ips[country].add(ip_text)

    per_quarter_rows = [
        {
            'Quarter': quarter,
            'IP Address': ip_text,
            'Hits': hits,
        }
        for (quarter, ip_text), hits in sorted(per_quarter.items())
    ]
    access_country_rows = []
    total_unique_ips = 0
    total_hits = 0
    for country in sorted(country_hits.keys()):
        unique_ip_count = len(country_ips[country])
        hit_count = country_hits[country]
        total_unique_ips += unique_ip_count
        total_hits += hit_count
        average = round_half_up(hit_count / unique_ip_count) if unique_ip_count else 0
        access_country_rows.append({
            'Country': country,
            'Unique IP Addresses': unique_ip_count,
            'No. of Hits': hit_count,
            'Average Hits per Address': average,
        })
    total_average = round_half_up(total_hits / total_unique_ips) if total_unique_ips else 0
    access_country_rows.append({
        'Country': 'Total',
        'Unique IP Addresses': total_unique_ips,
        'No. of Hits': total_hits,
        'Average Hits per Address': total_average,
    })

    return {
        'per_quarter_rows': per_quarter_rows,
        'access_country_rows': access_country_rows,
        'files_processed': files_processed,
        'lines_read': lines_read,
        'lines_counted': lines_counted,
        'total_unique_ips': total_unique_ips,
        'total_hits': total_hits,
        'countries_resolved': len([country for country in country_by_ip.values() if country != 'Unknown IP']),
    }


def major_release_statistics_jsp_path():
    return os.getenv(
        'ARE_MAJOR_RELEASE_STATISTICS_JSP',
        '/home/kira/app/Ingestion/MajorRelease/statistics.jsp',
    )


def parse_hit_quarter_label(label):
    match = HIT_LOG_QUARTER_RE.match(str(label or '').strip())
    if match is None:
        raise ValueError('Invalid quarter label: {}'.format(label))
    return int(match.group('year')), int(match.group('quarter'))


def build_hit_quarter_values(per_quarter_rows, existing_values):
    values = [int(value or 0) for value in existing_values]
    skipped_before_start = 0
    hit_delta_total = 0
    updated_indices = set()

    for row in per_quarter_rows:
        year, quarter = parse_hit_quarter_label(row.get('Quarter'))
        index = major_release_quarter_index(year, quarter)
        if index < 0:
            skipped_before_start += 1
            continue
        hits = int(row.get('Hits') or 0)
        if index >= len(values):
            values.extend([0] * (index + 1 - len(values)))
        values[index] = int(values[index] or 0) + hits
        hit_delta_total += hits
        updated_indices.add(index)

    return values, skipped_before_start, hit_delta_total, len(updated_indices)


def strip_html(value):
    return re.sub(r'<[^>]+>', '', str(value or '')).strip()


def parse_dataset_int(value):
    text = strip_html(value).replace(',', '')
    return int(float(text)) if text else 0


def build_country_dataset(existing_dataset, access_country_rows):
    country_index = {}
    country_order = []

    for row in existing_dataset:
        if not row:
            continue
        country = strip_html(row[0])
        if not country or country.lower() == 'total':
            continue
        country_index[country] = {
            'unique_ips': parse_dataset_int(row[1]) if len(row) > 1 else 0,
            'hits': parse_dataset_int(row[2]) if len(row) > 2 else 0,
        }
        country_order.append(country)

    added_countries = 0
    country_delta_hits = 0
    country_delta_unique_ips = 0
    for row in access_country_rows:
        country = str(row.get('Country') or '').strip()
        if not country or country.lower() == 'total':
            continue
        unique_ips = int(row.get('Unique IP Addresses') or 0)
        hits = int(row.get('No. of Hits') or 0)
        if country not in country_index:
            country_index[country] = {
                'unique_ips': 0,
                'hits': 0,
            }
            country_order.append(country)
            added_countries += 1
        country_index[country]['unique_ips'] += unique_ips
        country_index[country]['hits'] += hits
        country_delta_unique_ips += unique_ips
        country_delta_hits += hits

    dataset = []
    total_unique_ips = 0
    total_hits = 0
    for country in country_order:
        unique_ips = country_index[country]['unique_ips']
        hits = country_index[country]['hits']
        average = round_half_up(hits / unique_ips) if unique_ips else 0
        total_unique_ips += unique_ips
        total_hits += hits
        dataset.append([country, unique_ips, hits, average])

    total_average = round_half_up(total_hits / total_unique_ips) if total_unique_ips else 0
    dataset.append([
        '<b>Total</b>',
        '<b>{}</b>'.format(total_unique_ips),
        '<b>{}</b>'.format(total_hits),
        '<b>{}</b>'.format(total_average),
    ])

    return {
        'dataset': dataset,
        'added_countries': added_countries,
        'delta_unique_ips': country_delta_unique_ips,
        'delta_hits': country_delta_hits,
        'total_unique_ips': total_unique_ips,
        'total_hits': total_hits,
    }


def parse_country_dataset(raw_value):
    try:
        return ast.literal_eval(raw_value)
    except Exception as exc:
        raise ValueError('Could not parse countryDataSet: {}'.format(exc))


def update_hit_log_statistics(per_quarter_rows, access_country_rows, create_backup=True):
    jsp_path = major_release_statistics_jsp_path()
    with open(jsp_path, 'r', encoding='ISO-8859-1') as handle:
        content = handle.read()

    hits_pattern = re.compile(
        r"(name:\s*'Hits'\s*,[\s\S]*?data\s*:\s*)\[(.*?)\]",
        re.S,
    )
    hits_match = hits_pattern.search(content)
    if hits_match is None:
        raise ValueError("Could not find series 'Hits' in {}".format(jsp_path))

    country_pattern = re.compile(r'var\s+countryDataSet\s*=\s*(\[.*?\]);', re.S)
    country_match = country_pattern.search(content)
    if country_match is None:
        raise ValueError('Could not find countryDataSet in {}'.format(jsp_path))

    existing_hits = parse_javascript_number_array(hits_match.group(2))
    hit_values, skipped_before_start, hit_delta_total, hit_quarters_updated = build_hit_quarter_values(
        per_quarter_rows,
        existing_hits,
    )
    country_result = build_country_dataset(
        parse_country_dataset(country_match.group(1)),
        access_country_rows,
    )
    country_dataset = country_result['dataset']

    replacements = [
        (
            hits_match.start(),
            hits_match.end(),
            hits_match.group(1) + json.dumps(hit_values),
        ),
        (
            country_match.start(),
            country_match.end(),
            'var countryDataSet = {};'.format(json.dumps(country_dataset)),
        ),
    ]

    updated_content = content
    for start, end, replacement in sorted(replacements, reverse=True):
        updated_content = updated_content[:start] + replacement + updated_content[end:]

    backup_path = jsp_path + '.bak'
    if create_backup:
        with open(backup_path, 'w', encoding='ISO-8859-1') as handle:
            handle.write(content)
    with open(jsp_path, 'w', encoding='ISO-8859-1') as handle:
        handle.write(updated_content)

    return {
        'path': jsp_path,
        'backup_path': backup_path,
        'hit_quarters_updated': hit_quarters_updated,
        'hit_series_length': len(hit_values),
        'hit_total': sum(hit_values),
        'hit_delta_total': hit_delta_total,
        'country_rows_updated': len(country_dataset),
        'country_delta_hits': country_result['delta_hits'],
        'country_delta_unique_ips': country_result['delta_unique_ips'],
        'country_total_hits': country_result['total_hits'],
        'country_total_unique_ips': country_result['total_unique_ips'],
        'country_added': country_result['added_countries'],
        'skipped_quarter_rows_before_start': skipped_before_start,
    }


@app.route('/major_release/analyze_hit_logs', methods=['POST'])
def analyze_hit_logs():
    uploaded_files = request.files.getlist('files')
    if not uploaded_files:
        return jsonify({'status': 'error', 'message': 'Choose a folder with .txt log files first.'}), 400

    run_id = uuid.uuid4().hex[:12]
    upload_root = os.path.join(tempfile.gettempdir(), 'are_hit_log_uploads', run_id)
    output_root = os.getenv(
        'ARE_MAJOR_RELEASE_ROOT',
        os.path.dirname(os.getenv(
            'ARE_MAJOR_RELEASE_STATISTICS_JSP',
            '/home/kira/app/Ingestion/MajorRelease/statistics.jsp',
        )),
    )
    os.makedirs(upload_root, exist_ok=True)
    os.makedirs(output_root, exist_ok=True)

    saved_files = []
    for uploaded in uploaded_files:
        filename = os.path.basename(uploaded.filename.replace('\\', '/'))
        if not filename.lower().endswith('.txt'):
            continue
        path = os.path.join(upload_root, filename)
        uploaded.save(path)
        saved_files.append(path)

    if not saved_files:
        shutil.rmtree(upload_root, ignore_errors=True)
        return jsonify({'status': 'error', 'message': 'No .txt log files found in the selected folder.'}), 400

    try:
        result = analyze_hit_log_files(saved_files)
        per_quarter_path = os.path.join(output_root, 'perQuarter.xlsx')
        access_country_path = os.path.join(output_root, 'AccessCountry.xlsx')

        pd.DataFrame(result['per_quarter_rows']).to_excel(per_quarter_path, index=False)
        pd.DataFrame(result['access_country_rows']).to_excel(access_country_path, index=False)
        statistics_result = update_hit_log_statistics(
            result['per_quarter_rows'],
            result['access_country_rows'],
        )

        return jsonify({
            'status': 'success',
            'run_id': run_id,
            'files_processed': result['files_processed'],
            'lines_read': result['lines_read'],
            'lines_counted': result['lines_counted'],
            'total_unique_ips': result['total_unique_ips'],
            'total_hits': result['total_hits'],
            'countries_resolved': result['countries_resolved'],
            'per_quarter': {
                'path': per_quarter_path,
                'url': '../major_release/hit_log_result/perQuarter.xlsx',
            },
            'access_country': {
                'path': access_country_path,
                'url': '../major_release/hit_log_result/AccessCountry.xlsx',
            },
            'statistics_jsp': statistics_result,
            'country_note': 'Country lookup uses ip-api.com batch lookup. Failed/private/local IPs are grouped as Unknown IP.',
        })
    except Exception as exc:
        logging.exception('Hit log analysis failed')
        return jsonify({'status': 'error', 'message': str(exc)}), 500


@app.route('/major_release/hit_log_result/<path:filename>', methods=['GET'])
def download_hit_log_result(filename):
    if filename not in {'perQuarter.xlsx', 'AccessCountry.xlsx'}:
        return jsonify({'status': 'error', 'message': 'Invalid result file.'}), 400
    output_root = os.getenv(
        'ARE_MAJOR_RELEASE_ROOT',
        os.path.dirname(os.getenv(
            'ARE_MAJOR_RELEASE_STATISTICS_JSP',
            '/home/kira/app/Ingestion/MajorRelease/statistics.jsp',
        )),
    )
    return send_from_directory(output_root, filename, as_attachment=True)


@app.route('/datagen/generate/<string:generator_type>', methods=['POST'])
def generate_datagen(generator_type):
    normalized_type = {
        'measurement': 'MeasurementGEN',
        'measurementgen': 'MeasurementGEN',
        'measurements': 'MeasurementGEN',
        'metadata': 'MetadataGEN',
        'metadatagen': 'MetadataGEN',
    }.get(generator_type.lower())
    if normalized_type is None:
        return jsonify({'status': 'error', 'message': 'Invalid DataGEN type.'}), 400

    uploaded = request.files.get('xlsx')
    if uploaded is None or not uploaded.filename:
        return jsonify({'status': 'error', 'message': 'Choose an xlsx file first.'}), 400
    if not uploaded.filename.lower().endswith('.xlsx'):
        return jsonify({'status': 'error', 'message': 'Input file must be .xlsx.'}), 400

    outputdir = normalize_server_path(request.form.get('outputdir', ''))
    if not outputdir:
        return jsonify({'status': 'error', 'message': 'Output folder is required.'}), 400
    if not os.path.isabs(outputdir):
        return jsonify({'status': 'error', 'message': 'Output folder must be an absolute server path.'}), 400

    db_target = (request.form.get('database') or 'main').strip().lower()
    if db_target == 'review':
        database = cfg.dbselrev
    elif db_target == 'main':
        database = cfg.dbselmain
    else:
        return jsonify({'status': 'error', 'message': 'Database must be main or review.'}), 400

    run_id = uuid.uuid4().hex[:12]
    upload_root = os.path.join(tempfile.gettempdir(), 'are_datagen_uploads', run_id)
    os.makedirs(upload_root, exist_ok=True)
    xlsx_path = os.path.join(upload_root, os.path.basename(uploaded.filename.replace('\\', '/')))
    uploaded.save(xlsx_path)

    job_id = '{}_{}'.format(normalized_type, run_id)
    _prepare_archive_job('datagen', job_id, 'Starting {}'.format(normalized_type))
    r.set(_job_key('datagen', job_id, 'outputdir'), outputdir)
    r.set(_job_key('datagen', job_id, 'type'), normalized_type)
    r.set(_job_key('datagen', job_id, 'database'), database)
    thread = Thread(target=_run_datagen_job, args=(job_id, normalized_type, xlsx_path, outputdir, upload_root, database))
    thread.daemon = True
    thread.start()
    return jsonify({'status': 'started', 'job_id': job_id, 'type': normalized_type, 'outputdir': outputdir, 'database': database})


@app.route('/datagen/status/<string:job_id>', methods=['GET'])
def datagen_status(job_id):
    state = _get_archive_job('datagen', job_id)
    result = r.get(_job_key('datagen', job_id, 'result'))
    if result:
        try:
            state['result'] = json.loads(_decode_redis(result))
        except Exception:
            state['result'] = {}
    state['outputdir'] = _decode_redis(r.get(_job_key('datagen', job_id, 'outputdir')), '')
    state['type'] = _decode_redis(r.get(_job_key('datagen', job_id, 'type')), '')
    state['database'] = _decode_redis(r.get(_job_key('datagen', job_id, 'database')), '')
    return jsonify(state)


@app.route('/gifgen_folder', methods=['POST'])
def gifgen_folder():
    from threading import Thread
    data = request.get_json()
    def normalize_path(p):
        p = p.strip().strip('"').strip("'")
        import re
        # \\wsl.localhost\Ubuntu-24.04\home\... -> /home/...
        m = re.match(r'^\\\\wsl\.localhost\\[^\\]+\\(.*)', p)
        if m:
            return '/' + m.group(1).replace('\\', '/')
        # C:\Users\... or C:/Users/...
        m = re.match(r'^([A-Za-z]):[\\\/](.*)', p)
        if m:
            return '/mnt/' + m.group(1).lower() + '/' + m.group(2).replace('\\', '/')
        return p
    swcdir = normalize_path(data.get('swcdir', ''))
    outputdir = normalize_path(data.get('outputdir', ''))
    if not swcdir or not os.path.isdir(swcdir):
        return {'status': 'error', 'message': 'swcdir does not exist: {}'.format(swcdir)}
    if not outputdir:
        return {'status': 'error', 'message': 'outputdir is required'}
    if not os.path.isabs(outputdir):
        return {'status': 'error', 'message': 'outputdir must be an absolute server path'}
    try:
        threads = max(1, min(32, int(data.get('threads', 12))))
    except (TypeError, ValueError):
        return {'status': 'error', 'message': 'threads must be a number between 1 and 32'}
    resume = bool(data.get('resume', False))
    job_id = os.path.basename(swcdir.rstrip('/')) or 'custom_gifgen'
    t = Thread(target=io.genarchivegifs_frompath, args=(swcdir, outputdir, job_id, threads, resume))
    t.daemon = True
    t.start()
    return {'status': 'started', 'job_id': job_id}

@app.route('/pvec_folder', methods=['POST'])
def pvec_folder():
    from threading import Thread
    data = request.get_json()
    def normalize_path(p):
        p = p.strip().strip('"').strip("'")
        import re
        m = re.match(r'^\\\\wsl\.localhost\\[^\\]+\\(.*)', p)
        if m:
            return '/' + m.group(1).replace('\\', '/')
        m = re.match(r'^([A-Za-z]):[\\\/](.*)', p)
        if m:
            return '/mnt/' + m.group(1).lower() + '/' + m.group(2).replace('\\', '/')
        return p
    swcdir = normalize_path(data.get('swcdir', ''))
    outputdir = normalize_path(data.get('outputdir', ''))
    if not swcdir or not os.path.isdir(swcdir):
        return {'status': 'error', 'message': 'swcdir does not exist: {}'.format(swcdir)}
    if not outputdir:
        return {'status': 'error', 'message': 'outputdir is required'}
    if not os.path.isabs(outputdir):
        return {'status': 'error', 'message': 'outputdir must be an absolute server path'}
    try:
        threads = max(1, min(32, int(data.get('threads', 1))))
    except (TypeError, ValueError):
        return {'status': 'error', 'message': 'threads must be a number between 1 and 32'}
    job_id = os.path.basename(swcdir.rstrip('/')) or 'custom_pvec'
    if r.get('topvec_lock'):
        return {'status': 'error', 'message': 'Another TOPVEC job is already running'}
    r.set('topvec_lock', job_id, ex=86400)
    t = Thread(target=io.genpvecs_frompath, args=(swcdir, outputdir, job_id, threads))
    t.daemon = True
    t.start()
    return {'status': 'started', 'job_id': job_id}


@app.route('/readarchive/<string:archive>', methods=['GET'])
def readarchive(archive):
    result = io.getfiles(archive)
    return result

@app.route('/readarchive_steps/<string:archive>', methods=['POST'])
def readarchive_steps(archive):
    if _archive_job_is_running('read', archive):
        return {'status': 'running', 'job_id': archive}
    data = request.get_json() or {}
    locked, owner = _claim_archive_workflow_lock('read', archive)
    if not locked:
        return {'status': 'error', 'message': 'Another archive workflow is running: {}'.format(owner)}
    _prepare_archive_job('read', archive, 'Starting Read Archive for {}'.format(archive))
    t = Thread(target=_run_read_archive_job, args=(archive, data.get('steps', {})))
    t.daemon = True
    t.start()
    return {'status': 'started', 'job_id': archive}

#reading status
@app.route('/checkreadarchive/<string:archive>', methods=['GET'])
def checkreadarchive(archive):
    job_state = _get_archive_job('read', archive)
    if job_state['status'] != 'idle':
        return job_state
    status = r.get(f"{archive}_read_status")
    progress = r.get(f"{archive}_read_progress")
    message = r.get(f"{archive}_read_message")

    return {
        'status': status.decode() if isinstance(status, bytes) else (status or 'idle'),
        'progress': float(progress) if progress is not None else 0,
        'message': message.decode() if isinstance(message, bytes) else (message or '')
    }


@app.route('/stopreadarchive/<string:archive>', methods=['POST'])
def stopreadarchive(archive):
    r.set(_job_key('read', archive, 'stop'), '1')
    _set_archive_job('read', archive, message='Stop requested. Finishing current read stage before stopping.', status='stopping')
    return _get_archive_job('read', archive)


@app.route('/revertarchive/<string:archive>', methods=['GET'])
def revertarchive(archive):
    result = io.revertarchive(archive)
    return result

@app.route('/deleteneurons', methods=['POST'])
def deleteneurons():
    anarchive = request.get_json()
    neuronfolder = anarchive['name']
    return io.revertarchive(neuronfolder)

@app.route('/archiveneurons', methods=['POST'])
def archiveneurons():
    anarchive = request.get_json()
    neuronfolder = anarchive['name']
    io.transfertocng(neuronfolder)
    for item in anarchive['neurons']:
        com.archiveneuron(item['neuron_name'])
    com.deleteingestedarchive(neuronfolder)
    logging.info("archiveneurons = {}".format(neuronfolder))
    return {"status": "success"}


@app.route('/deingestarchive/<string:archive>', methods=['GET'])
def deingestarchive(archive):
    result = io.deingestarchive(archive)
    return result


@app.route('/revertfrommain/<string:archive>', methods=['GET'])
def revertfrommain(archive):
    result = io.revertfrommain(archive)
    return result

@app.route('/genwinjsp/<string:archive>', methods=['GET'])
def genwinjsp(archive):
    try:
        now = datetime.datetime.now()
        dt_string = now.strftime("%Y-%m-%d")
        cfg.sshdir = cfg.sshreviewdir
        (version,nneurons) = io.genwinjsp(archive)
        io.writeendings(archive)
        io.updateinforev(archive,version,dt_string)
        io.reviewworkflow()
        return {"status": "success"}
    except Exception as identifier:
        logging.exception("Error when generating win.jsp")
        return {"status": "error"}
    

@app.route('/ingestneuron/<string:neuron_name>',  methods=['GET'])
def ingestneuron(neuron_name):
    cfg.sshdir = cfg.sshreviewdir
    neuronResults = ingest.ingestneuron(neuron_name)
    return neuronResults

@app.route('/ingestarchive/<string:folder_name>',  methods=['GET'])
def ingestarchive(folder_name):
    if _archive_job_is_running('ingest', folder_name):
        return {'status': 'running', 'job_id': folder_name}
    threads = _parse_ingest_threads(request.args.get('threads'))
    locked, owner = _claim_archive_workflow_lock('ingest', folder_name)
    if not locked:
        return {'status': 'error', 'message': 'Another archive workflow is running: {}'.format(owner)}
    _prepare_archive_job('ingest', folder_name, 'Starting ingest for {} with {} thread(s)'.format(folder_name, threads))
    r.set(_job_key('ingest', folder_name, 'threads'), threads)
    t = Thread(target=_run_ingest_archive_job, args=(folder_name, threads))
    t.daemon = True
    t.start()
    return {'status': 'started', 'job_id': folder_name, 'threads': threads}


@app.route('/checkingestarchive/<string:folder_name>', methods=['GET'])
def checkingestarchive(folder_name):
    return _get_archive_job('ingest', folder_name)


@app.route('/stopingestarchive/<string:folder_name>', methods=['POST'])
def stopingestarchive(folder_name):
    r.set(_job_key('ingest', folder_name, 'stop'), '1')
    _set_archive_job('ingest', folder_name, message='Stop requested. Finishing current neuron before stopping.', status='stopping')
    return _get_archive_job('ingest', folder_name)

@app.route('/deleteneuron/<string:neuron_name>',  methods=['GET'])
def deleteneuron(neuron_name):
    cfg.sshdir = cfg.sshreviewdir
    neuronResults = io.deleteneuron(neuron_name)
    return neuronResults

@app.route('/handleduplicate/<string:neuron_name>/<string:action>',  methods=['GET'])
def handleduplicate(neuron_name,action):
    com.pginsert('duplicateactions',{
        'neuron_name': neuron_name,
        'action': action
    })
    com.deletefromjson('dupname',neuron_name,'ui/assets/ajax/duplicates2023b.json')
    return {"status": "success"}


'''@app.route('/tweetneuron/<string:neuron_name>/<string:archive>/',  methods=['GET'])
def tweetneuron(neuron_name,archive):
    cfg.sshdir = cfg.sshreviewdir
    neuronResults = com.tweetneuron(neuron_name,archive)
    return neuronResults'''

@app.route('/tweetneuron/<string:neuron_name>/<string:archive>/',  methods=['GET'])
def tweetneurons(neuron_name,archive):
    cfg.sshdir = cfg.sshreviewdir
    version = com.getcurrentversions('pubversion')
    (neuronlist,neuronids) = com.getarchiveneurons(archive)
    nneurons = len(neuronlist)
    if nneurons == 1:
        plural = ''
    else:
        plural = 's'
    #foldername = io.namefromfolder(archive)
    #logging.info("app.py foldername = {}".format(foldername))

    csvfile = cfg.readyarchives
    folder = io.tweetfolder(archive, csvfile)
    folder_name = com.getfoldername(archive)
    logging.info("app.py folders name = {}".format(folder_name))


    tweet_id = io.publishtweets(version,nneurons,archive, neuron_name, folder_name)
    tweet_url = "https://twitter.com/NeuroMorphoOrg/status/{}".format(tweet_id)
    embed_code = io.embedded_tweet(tweet_url)
    io.tweet_index_embed(embed_code)
    io.tweet_index_embed_remove()

    return plural



@app.route('/exporttomain/<string:archive>',  methods=['GET'])
def exporttomain(archive):
    if _archive_job_is_running('exportmain', archive):
        return {'status': 'running', 'job_id': archive}
    threads = _parse_ingest_threads(request.args.get('threads'))
    locked, owner = _claim_archive_workflow_lock('exportmain', archive)
    if not locked:
        return {'status': 'error', 'message': 'Another archive workflow is running: {}'.format(owner)}
    _prepare_archive_job('exportmain', archive, 'Starting Export to main for {} with {} thread(s)'.format(archive, threads))
    r.set(_job_key('exportmain', archive, 'threads'), threads)
    t = Thread(target=_run_export_to_main_job, args=(archive, threads))
    t.daemon = True
    t.start()
    return {'status': 'started', 'job_id': archive, 'threads': threads}


@app.route('/checkexporttomain/<string:archive>', methods=['GET'])
def checkexporttomain(archive):
    return _get_archive_job('exportmain', archive)


@app.route('/stopexporttomain/<string:archive>', methods=['POST'])
def stopexporttomain(archive):
    r.set(_job_key('exportmain', archive, 'stop'), '1')
    _set_archive_job('exportmain', archive, message='Stop requested. Finishing current neuron before stopping.', status='stopping')
    return _get_archive_job('exportmain', archive)


@app.route('/create_tweet', methods=['POST'])
def create_tweet():
    data = request.get_json()
    tweet_link = data.get('tweet_link')

    #tweet_id = 1707394627295424633
    tweet_id = io.createtweet(tweet_link, tweet_link)
    tweet_url = "https://twitter.com/NeuroMorphoOrg/status/{}".format(tweet_id)
    embed_code = io.embedded_tweet(tweet_url)
    io.tweet_index_embed(embed_code)
    io.tweet_index_embed_remove()

    return jsonify({"message": "Tweet created successfully"}), 200

@app.route('/create_tweets', methods=['POST'])
def create_tweets():
    data = request.get_json()
    tweet_link = data.get('tweet_links')

    #tweet_id = 1707394627295424633
    tweet_id = io.createtweets(tweet_link, tweet_link)
    tweet_url = "https://twitter.com/NeuroMorphoOrg/status/{}".format(tweet_id)
    embed_code = io.embedded_tweet(tweet_url)
    io.tweet_index_embed(embed_code)
    io.tweet_index_embed_remove()

    return jsonify({"message": "Tweet created successfully"}), 200


@app.route('/create_tweetc_customize', methods=['POST'])
def create_tweetc_customize():
    data = request.get_json()
    tweet_link = data.get('tweet_link_customize')

    logging.info(tweet_link)

    tweet_id = io.createtweetcustomize(tweet_link)
    tweet_url = "https://twitter.com/NeuroMorphoOrg/status/{}".format(tweet_id)
    embed_code = io.embedded_tweet(tweet_url)
    io.tweet_index_embed(embed_code)
    io.tweet_index_embed_remove()

    return jsonify({"message": "Tweet created successfully"}), 200

def mysql_identifier(name):
    return "`{}`".format(str(name).replace("`", "``"))


MAJOR_RELEASE_DOWNLOAD_REPORTS = {
    'species': {
        'label': 'Species',
        'id': 'species.species_id',
        'select': 'species.species',
        'join': 'JOIN {main_db}.species AS species ON n.species_id = species.species_id',
        'group': 'species.species_id, species.species',
        'order': 'species.species',
    },
    'cell_type': {
        'label': 'Cell Type',
        'id': 'celltype.class2_id',
        'select': 'celltype.class2',
        'join': 'JOIN {main_db}.neuron_class2 AS celltype ON n.class2_id = celltype.class2_id',
        'group': 'celltype.class2_id, celltype.class2',
        'order': 'celltype.class2',
    },
    'archive': {
        'label': 'Archive',
        'id': 'archive.archive_id',
        'select': 'archive.archive_name',
        'join': 'JOIN {main_db}.archive AS archive ON n.archive_id = archive.archive_id',
        'group': 'archive.archive_id, archive.archive_name',
        'order': 'archive.archive_name',
    },
    'brain_region': {
        'label': 'Brain Region',
        'id': 'region.region1_id',
        'select': 'region.region1',
        'join': 'JOIN {main_db}.neuron_region1 AS region ON n.region1_id = region.region1_id',
        'group': 'region.region1_id, region.region1',
        'order': 'region.region1',
    },
}

MAJOR_RELEASE_DATASETS = {
    'species': 'speciesDataSet',
    'cell_type': 'cellDataSet',
    'archive': 'archiveDataSet',
    'brain_region': 'brainRegionDataSet',
}

MAJOR_RELEASE_QUARTER_SERIES = {
    'AuxillaryFiles': 'Auxillary Files',
    'NeuronFiles': 'Neuron Files',
}

MAJOR_RELEASE_QUARTER_START_YEAR = 2006
MAJOR_RELEASE_QUARTER_START_QUARTER = 3


def round_half_up(value):
    return int(float(value) + 0.5)


def bold(value):
    return '<b>{}</b>'.format(value)


def update_major_release_statistics(report_type, rows, create_backup=True):
    dataset_name = MAJOR_RELEASE_DATASETS[report_type]
    jsp_path = os.getenv(
        'ARE_MAJOR_RELEASE_STATISTICS_JSP',
        '/home/kira/app/Ingestion/MajorRelease/statistics.jsp',
    )
    months = float(os.getenv('ARE_MAJOR_RELEASE_MONTHS', '42'))

    with open(jsp_path, 'r', encoding='ISO-8859-1') as handle:
        content = handle.read()

    pattern = re.compile(r'var\s+{}\s*=\s*(\[.*?\]);'.format(re.escape(dataset_name)), re.S)
    match = pattern.search(content)
    if match is None:
        raise ValueError('Could not find {} in {}'.format(dataset_name, jsp_path))

    dataset = ast.literal_eval(match.group(1))
    existing_rows = dataset[:-1]
    row_index = {str(row[0]): row for row in existing_rows}
    new_labels = {str(row['label']) for row in rows}
    updated_rows = []

    for row in rows:
        label = str(row['label'])
        number_of_cells = int(row['NumberOfCells'] or 0)
        new_downloads = int(row['Totalnumber'] or 0)
        current = row_index.get(label)
        if current is None:
            current = [label, 0, 0, 0, 0]
            row_index[label] = current

        total_downloads = int(current[2] or 0) + new_downloads
        average_per_cell = round_half_up(total_downloads / number_of_cells) if number_of_cells else 0
        average_per_cell_per_month = round_half_up(average_per_cell / months) if months else 0

        current[1] = number_of_cells
        current[2] = total_downloads
        current[3] = average_per_cell
        current[4] = average_per_cell_per_month
        updated_rows.append(current)

    existing_order = {str(row[0]): index for index, row in enumerate(existing_rows)}
    updated_rows.sort(key=lambda row: existing_order.get(str(row[0]), len(existing_order)))
    removed_rows = [row for row in existing_rows if str(row[0]) not in new_labels]

    total_cells = sum(int(row[1] or 0) for row in updated_rows)
    total_downloads = sum(int(row[2] or 0) for row in updated_rows)
    total_average = round_half_up(
        sum(int(row[3] or 0) for row in updated_rows) / len(updated_rows)
    ) if updated_rows else 0
    total_average_per_month = round_half_up(
        sum(int(row[4] or 0) for row in updated_rows) / len(updated_rows)
    ) if updated_rows else 0

    updated_dataset = updated_rows + [[
        bold('Total'),
        bold(total_cells),
        bold(total_downloads),
        bold(total_average),
        bold(total_average_per_month),
    ]]
    replacement = 'var {} = {};'.format(dataset_name, json.dumps(updated_dataset))
    backup_path = jsp_path + '.bak'
    if create_backup:
        with open(backup_path, 'w', encoding='ISO-8859-1') as handle:
            handle.write(content)
    with open(jsp_path, 'w', encoding='ISO-8859-1') as handle:
        handle.write(content[:match.start()] + replacement + content[match.end():])

    return {
        'dataset': dataset_name,
        'path': jsp_path,
        'rows_updated': len(rows),
        'rows_removed': len(removed_rows),
        'total_cells': total_cells,
        'total_downloads': total_downloads,
        'backup_path': backup_path,
    }


def major_release_quarter_index(year, quarter):
    return (
        (int(year) - MAJOR_RELEASE_QUARTER_START_YEAR) * 4
        + (int(quarter) - MAJOR_RELEASE_QUARTER_START_QUARTER)
    )


def parse_javascript_number_array(raw_value):
    if not raw_value.strip():
        return []
    return [int(value) for value in ast.literal_eval('[' + raw_value + ']')]


def update_downloads_per_quarter_statistics(rows, create_backup=True):
    jsp_path = os.getenv(
        'ARE_MAJOR_RELEASE_STATISTICS_JSP',
        '/home/kira/app/Ingestion/MajorRelease/statistics.jsp',
    )

    with open(jsp_path, 'r', encoding='ISO-8859-1') as handle:
        content = handle.read()

    series_values = {}
    series_matches = {}
    for row_key, series_name in MAJOR_RELEASE_QUARTER_SERIES.items():
        pattern = re.compile(
            r"(name:\s*'{}'[\s\S]*?data\s*:\s*)\[(.*?)\]".format(
                re.escape(series_name)
            ),
            re.S,
        )
        match = pattern.search(content)
        if match is None:
            raise ValueError("Could not find series '{}' in {}".format(series_name, jsp_path))
        series_values[row_key] = parse_javascript_number_array(match.group(2))
        series_matches[row_key] = match

    normalized_rows = []
    for row in rows:
        year = int(row.get('year') or 0)
        quarter = int(row.get('quarter') or 0)
        if quarter < 1 or quarter > 4:
            raise ValueError('Invalid quarter {}'.format(quarter))
        index = major_release_quarter_index(year, quarter)
        if index < 0:
            raise ValueError(
                '{}Q{} is before the JSP chart start quarter {}Q{}'.format(
                    year,
                    quarter,
                    MAJOR_RELEASE_QUARTER_START_YEAR,
                    MAJOR_RELEASE_QUARTER_START_QUARTER,
                )
            )
        normalized_rows.append({
            'year': year,
            'quarter': quarter,
            'label': '{}Q{}'.format(year, quarter),
            'index': index,
            'NeuronFiles': int(row.get('NeuronFiles') or 0),
            'AuxillaryFiles': int(row.get('AuxillaryFiles') or 0),
        })

    for row in normalized_rows:
        for row_key in MAJOR_RELEASE_QUARTER_SERIES.keys():
            values = series_values[row_key]
            if row['index'] >= len(values):
                values.extend([0] * (row['index'] + 1 - len(values)))
            values[row['index']] = int(values[row['index']] or 0) + row[row_key]

    updated_content = content
    replacements = []
    for row_key in ('NeuronFiles', 'AuxillaryFiles'):
        match = series_matches[row_key]
        replacement = match.group(1) + json.dumps(series_values[row_key])
        replacements.append((match.start(), match.end(), replacement))

    for start, end, replacement in sorted(replacements, reverse=True):
        updated_content = updated_content[:start] + replacement + updated_content[end:]

    backup_path = jsp_path + '.bak'
    if create_backup:
        with open(backup_path, 'w', encoding='ISO-8859-1') as handle:
            handle.write(content)
    with open(jsp_path, 'w', encoding='ISO-8859-1') as handle:
        handle.write(updated_content)

    return {
        'path': jsp_path,
        'backup_path': backup_path,
        'rows_updated': len(normalized_rows),
        'total_neuron_files': sum(row['NeuronFiles'] for row in normalized_rows),
        'total_auxillary_files': sum(row['AuxillaryFiles'] for row in normalized_rows),
        'start_quarter': normalized_rows[0]['label'] if normalized_rows else None,
        'end_quarter': normalized_rows[-1]['label'] if normalized_rows else None,
    }


def normalize_download_report_rows(rows):
    normalized = []
    for row in rows:
        label = str(row.get('label', '')).strip()
        if not label:
            continue
        normalized.append({
            'label': label,
            'NumberOfCells': int(row.get('NumberOfCells') or 0),
            'Totalnumber': int(row.get('Totalnumber') or 0),
        })
    return normalized


@app.route('/major_release/revert_statistics', methods=['POST'])
def revert_major_release_statistics():
    jsp_path = os.getenv(
        'ARE_MAJOR_RELEASE_STATISTICS_JSP',
        '/home/kira/app/Ingestion/MajorRelease/statistics.jsp',
    )
    backup_path = jsp_path + '.bak'
    if not os.path.exists(backup_path):
        return jsonify({
            "status": "error",
            "message": "No backup found to revert.",
        }), 404

    with open(jsp_path, 'r', encoding='ISO-8859-1') as handle:
        current_content = handle.read()
    with open(backup_path, 'r', encoding='ISO-8859-1') as handle:
        backup_content = handle.read()
    with open(jsp_path, 'w', encoding='ISO-8859-1') as handle:
        handle.write(backup_content)
    with open(backup_path, 'w', encoding='ISO-8859-1') as handle:
        handle.write(current_content)

    return jsonify({
        "status": "success",
        "message": "statistics.jsp reverted.",
        "path": jsp_path,
        "backup_path": backup_path,
    })


@app.route('/major_release/downloads_report/<string:report_type>', methods=['POST'])
def downloads_report(report_type):
    report = MAJOR_RELEASE_DOWNLOAD_REPORTS.get(report_type)
    if report is None:
        return jsonify({"status": "error", "message": "Invalid report type"}), 400

    data = request.get_json() or {}
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    try:
        start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
    except Exception:
        return jsonify({"status": "error", "message": "Invalid date range"}), 400

    if start_date > end_date:
        return jsonify({"status": "error", "message": "Start date must be before end date"}), 400

    logging_db = os.getenv('ARE_MYSQL_LOGGING_DB', 'LoggingData')
    main_db = cfg.dbselmain
    main_db_sql = mysql_identifier(main_db)
    join_sql = report['join'].format(main_db=main_db_sql)
    query = """
        SELECT
            cell_counts.label,
            cell_counts.NumberOfCells,
            COALESCE(downloads.Totalnumber, 0) AS Totalnumber
        FROM (
            SELECT
                {id_column} AS report_id,
                {select_column} AS label,
                COUNT(DISTINCT n.neuron_id) AS NumberOfCells
            FROM
                {main_db}.neuron AS n
            {join_sql}
            GROUP BY
                {group_column}
        ) AS cell_counts
        LEFT JOIN (
            SELECT
                {id_column} AS report_id,
                SUM(
                    (log.CNGVersion = TRUE) +
                    (log.RemainingIssues = TRUE) +
                    (log.SourceVersion = TRUE) +
                    (log.StandardizationLog = TRUE)
                ) AS Totalnumber
            FROM
                {logging_db}.logdownload AS log
            JOIN
                {main_db}.neuron AS n
            ON
                log.Neuronname = n.neuron_name
            {join_sql}
            WHERE
                log.DateVisited >= %s AND log.DateVisited <= %s
            GROUP BY
                {id_column}
        ) AS downloads
        ON
            cell_counts.report_id = downloads.report_id
        ORDER BY
            Totalnumber DESC, cell_counts.label ASC
    """.format(
        id_column=report['id'],
        select_column=report['select'],
        logging_db=mysql_identifier(logging_db),
        main_db=main_db_sql,
        join_sql=join_sql,
        group_column=report['group'],
    )

    conn = None
    try:
        conn = mysql.connector.connect(
            user=cfg.dbuser,
            password=cfg.dbpass,
            host=cfg.dbhost,
            database=main_db,
            auth_plugin=cfg.db_auth_plugin,
        )
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, (start_date, end_date))
        rows = cursor.fetchall()
        cursor.close()
        for row in rows:
            row['NumberOfCells'] = int(row['NumberOfCells'] or 0)
            row['Totalnumber'] = int(row['Totalnumber'] or 0)
        total = sum(row['Totalnumber'] for row in rows)
        total_cells = sum(row['NumberOfCells'] for row in rows)
        return jsonify({
            "status": "success",
            "report_type": report_type,
            "label": report['label'],
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "total": total,
            "total_cells": total_cells,
            "data": rows,
        })
    except Exception as exc:
        logging.exception("Error querying major release downloads report")
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        if conn is not None:
            conn.close()


@app.route('/major_release/downloads_per_quarter', methods=['POST'])
def downloads_per_quarter():
    data = request.get_json() or {}
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    try:
        start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
    except Exception:
        return jsonify({"status": "error", "message": "Invalid date range"}), 400

    if start_date > end_date:
        return jsonify({"status": "error", "message": "Start date must be before end date"}), 400

    logging_db = os.getenv('ARE_MYSQL_LOGGING_DB', 'LoggingData')
    logging_db_sql = mysql_identifier(logging_db)
    start_year = start_date.year
    start_quarter = ((start_date.month - 1) // 3) + 1
    end_year = end_date.year
    end_quarter = ((end_date.month - 1) // 3) + 1

    query = """
        SELECT
            yr,
            qtr,
            SUM(neuron) AS NeuronFiles,
            SUM(aux) AS AuxillaryFiles
        FROM (
            SELECT
                YEAR(DateVisited) AS yr,
                QUARTER(DateVisited) AS qtr,
                SUM(
                    (CNGVersion = TRUE) +
                    (RemainingIssues = TRUE) +
                    (SourceVersion = TRUE) +
                    (StandardizationLog = TRUE)
                ) AS neuron,
                0 AS aux
            FROM
                {logging_db}.previous_logdownload
            WHERE
                DateVisited >= %s AND DateVisited <= %s
            GROUP BY
                yr, qtr

            UNION ALL

            SELECT
                YEAR(DateVisited) AS yr,
                QUARTER(DateVisited) AS qtr,
                SUM(
                    (CNGVersion = TRUE) +
                    (RemainingIssues = TRUE) +
                    (SourceVersion = TRUE) +
                    (StandardizationLog = TRUE)
                ) AS neuron,
                SUM(
                    (Signature = TRUE) +
                    (RemainingIssues = TRUE) +
                    (SourceVersion = TRUE) +
                    (StandardizationLog = TRUE)
                ) AS aux
            FROM
                {logging_db}.logdownload
            WHERE
                DateVisited >= %s AND DateVisited <= %s
            GROUP BY
                yr, qtr
        ) AS downloads
        GROUP BY
            yr, qtr
        ORDER BY
            yr, qtr
    """.format(logging_db=logging_db_sql)

    conn = None
    try:
        conn = mysql.connector.connect(
            user=cfg.dbuser,
            password=cfg.dbpass,
            host=cfg.dbhost,
            database=logging_db,
            auth_plugin=cfg.db_auth_plugin,
        )
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, (start_date, end_date, start_date, end_date))
        db_rows = cursor.fetchall()
        cursor.close()

        row_index = {
            (int(row['yr']), int(row['qtr'])): row
            for row in db_rows
        }
        rows = []
        year = start_year
        quarter = start_quarter
        while (year < end_year) or (year == end_year and quarter <= end_quarter):
            row = row_index.get((year, quarter), {})
            neuron_files = int(row.get('NeuronFiles') or 0)
            auxillary_files = int(row.get('AuxillaryFiles') or 0)
            rows.append({
                'year': year,
                'quarter': quarter,
                'label': '{}Q{}'.format(year, quarter),
                'NeuronFiles': neuron_files,
                'AuxillaryFiles': auxillary_files,
            })
            quarter += 1
            if quarter > 4:
                quarter = 1
                year += 1

        return jsonify({
            'status': 'success',
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'start_quarter': '{}Q{}'.format(start_year, start_quarter),
            'end_quarter': '{}Q{}'.format(end_year, end_quarter),
            'total_neuron_files': sum(row['NeuronFiles'] for row in rows),
            'total_auxillary_files': sum(row['AuxillaryFiles'] for row in rows),
            'data': rows,
        })
    except Exception as exc:
        logging.exception("Error querying downloads per quarter")
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        if conn is not None:
            conn.close()


@app.route('/major_release/build_downloads_per_quarter', methods=['POST'])
def build_downloads_per_quarter():
    data = request.get_json() or {}
    rows = data.get('rows') or []
    if not rows:
        return jsonify({
            "status": "error",
            "message": "Run Downloads per Quarter before building.",
        }), 400

    try:
        result = update_downloads_per_quarter_statistics(rows)
        return jsonify({
            "status": "success",
            "message": (
                "statistics.jsp Downloads per Quarter updated from {} to {}."
                .format(result['start_quarter'], result['end_quarter'])
            ),
            **result,
        })
    except Exception as exc:
        logging.exception("Error building downloads per quarter statistics")
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route('/major_release/downloads_by_species', methods=['POST'])
def downloads_by_species():
    return downloads_report('species')


@app.route('/major_release/build_downloads_by', methods=['POST'])
def build_downloads_by():
    data = request.get_json() or {}
    reports = data.get('reports') or {}
    normalized_reports = {}
    for report_type, rows in reports.items():
        if report_type not in MAJOR_RELEASE_DOWNLOAD_REPORTS:
            return jsonify({
                "status": "error",
                "message": "Invalid report type: {}".format(report_type),
            }), 400
        normalized_rows = normalize_download_report_rows(rows or [])
        if not normalized_rows:
            return jsonify({
                "status": "error",
                "message": "No rows to build for {}".format(report_type),
            }), 400
        normalized_reports[report_type] = normalized_rows

    if not normalized_reports:
        return jsonify({
            "status": "error",
            "message": "No report data supplied. Run reports first.",
        }), 400

    jsp_path = os.getenv(
        'ARE_MAJOR_RELEASE_STATISTICS_JSP',
        '/home/kira/app/Ingestion/MajorRelease/statistics.jsp',
    )
    backup_path = jsp_path + '.bak'
    with open(jsp_path, 'r', encoding='ISO-8859-1') as handle:
        original_content = handle.read()
    with open(backup_path, 'w', encoding='ISO-8859-1') as handle:
        handle.write(original_content)

    updates = {}
    for report_type, rows in normalized_reports.items():
        updates[report_type] = update_major_release_statistics(
            report_type,
            rows,
            create_backup=False,
        )

    return jsonify({
        "status": "success",
        "message": "statistics.jsp updated.",
        "updates": updates,
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
