import mysql.connector
import numpy as np
from flask import Flask, send_from_directory, jsonify, request
from flask_cors import CORS, cross_origin
import json, requests, os
from copy import deepcopy
import datetime
import redis
import time
import logging
import subprocess
import tempfile
import shutil
from are import cfg,io,com,utils,ingest,ingestdiameter
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
    
    if progress is None:
        progress = 0
    else:
        progress = float(progress)
    result = {
        'status': str(status),
        'progress': progress
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

    if db_target not in {'mysql_review', 'mysql_main', 'postgres'}:
        return {'status': 'error', 'message': 'Invalid database target.'}, 400
    if dump_file is None or not dump_file.filename:
        return {'status': 'error', 'message': 'No dump file uploaded.'}, 400

    temp_path = None
    try:
        suffix = os.path.splitext(dump_file.filename)[1] or '.sql'
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=export_root) as tmp:
            dump_file.save(tmp)
            temp_path = tmp.name

        if db_target == 'mysql_review':
            mysql_import_user = os.getenv('ARE_MYSQL_DUMP_USER', 'root')
            mysql_import_password = os.getenv('ARE_MYSQL_ROOT_PASSWORD', os.getenv('ARE_MYSQL_PASSWORD', ''))
            mysql_cmd = [
                'mysql',
                '--host', cfg.dbhost,
                '--user', mysql_import_user,
                cfg.dbselrev,
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
            imported_db = cfg.dbselrev
        elif db_target == 'mysql_main':
            mysql_import_user = os.getenv('ARE_MYSQL_DUMP_USER', 'root')
            mysql_import_password = os.getenv('ARE_MYSQL_ROOT_PASSWORD', os.getenv('ARE_MYSQL_PASSWORD', ''))
            mysql_cmd = [
                'mysql',
                '--host', cfg.dbhost,
                '--user', mysql_import_user,
                cfg.dbselmain,
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
            imported_db = cfg.dbselmain
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


@app.route('/readarchive/<string:archive>', methods=['GET'])
def readarchive(archive):
    result = io.getfiles(archive)
    return result

#reading status
@app.route('/checkreadarchive/<string:archive>', methods=['GET'])
def checkreadarchive(archive):
    status = r.get(f"{archive}_read_status")
    progress = r.get(f"{archive}_read_progress")
    message = r.get(f"{archive}_read_message")

    return {
        'status': status.decode() if isinstance(status, bytes) else (status or 'idle'),
        'progress': float(progress) if progress is not None else 0,
        'message': message.decode() if isinstance(message, bytes) else (message or '')
    }


@app.route('/revertarchive/<string:archive>', methods=['GET'])
def revertarchive(archive):
    result = io.revertarchive(archive)
    return result

@app.route('/deleteneurons', methods=['POST'])
def deleteneurons():
    anarchive = request.get_json()
    neuronfolder = anarchive['name']
    for item in anarchive['neurons']:
        io.deleteneuron(item['neuron_name'])
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
    cfg.sshdir = cfg.sshreviewdir
    neuronResults = ingest.ingestarchive(folder_name)
    logging.info("check 1 {}".format(neuronResults))
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
    try:    
        now = datetime.datetime.now()
        dt_string = now.strftime("%Y-%m-%d")
        logging.info("Dtstring: {}".format(dt_string))
        cfg.sshdir = cfg.sshreviewdir
        cfg.dbsel = cfg.dbselmain
        io.mainrelease(archive,dt_string)
        cfg.sshdir = cfg.sshmaindir
        
        (version,nneurons) = io.genwinjsp(archive, dt_string)
        io.writeendings(archive)
        io.updateinfo(archive,version,dt_string)
        # Temporarily disable the main publish workflow trigger.
        # io.mainworkflow()
        io.updatetickertape()
        results = {
            "data" : "Archive {} exported".format(archive),
            "status": "success"
        }
        #io.publishtweet(version,nneurons,archive)
    except Exception:
        logging.exception("Error during export to main site of archive {}".format(archive))
        results = {
            "status": "error"
        }    
    cfg.sshdir = cfg.sshreviewdir
    cfg.dbsel = cfg.dbselrev
    return results


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




if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
