import subprocess
from datetime import datetime
import requests
import os
import zipfile
import io
import pathlib
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, flash, request, redirect, url_for, send_file
from werkzeug.utils import secure_filename
from flask_cors import CORS, cross_origin


UPLOAD_FOLDER = 'input/'
ALLOWED_EXTENSIONS = {'swc'}

app = Flask(__name__)
CORS(app)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    """
    docstring
    """
    return  {"message": "Welcome to the SWC to PVecs API. Use the endpoints to upload files, calculate PVecs, and download results."}

@app.route('/calcpvecs', methods=['GET'])
def calcpvecs():
    """
    docstring
    """
    function_type = request.args.get('function_type', '1')
    if function_type not in {'0', '1', '2', '3', '4', '5'}:
        function_type = '1'
    try:
        threads = max(1, min(32, int(request.args.get('threads', '1'))))
    except ValueError:
        threads = 1

    input_files = sorted(
        item for item in os.listdir('input')
        if item.lower().endswith('.swc') and os.path.isfile(os.path.join('input', item))
    )
    skipped = []

    def convert_one(filename):
        tmpdir = tempfile.mkdtemp(prefix='swc2pvec_', dir='/tmp')
        try:
            shutil.copy2(os.path.join('/app/input', filename), os.path.join(tmpdir, filename))
            subprocess.run(
                ["java", "FTMain", tmpdir, "../des", function_type],
                cwd="/app/java",
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
            )
            return None
        except subprocess.CalledProcessError as exc:
            return {
                "file": filename,
                "error": (exc.stdout or str(exc)).strip().splitlines()[-1] if (exc.stdout or str(exc)).strip() else str(exc),
            }
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(convert_one, filename) for filename in input_files]
        for future in as_completed(futures):
            result = future.result()
            if result:
                skipped.append(result)

    des_count = len([item for item in os.listdir('des') if item.endswith('.des')])
    if des_count == 0:
        return {
            "result": "error",
            "message": "No .des files were generated",
            "input_count": len(input_files),
            "skipped": skipped[:50],
            "skipped_count": len(skipped),
        }, 500

    subprocess.run(["./main", "des", "pdg/"], check=True)
    subprocess.run(["./vectorization", "pdg/", 'output/'], check=True)

    output_count = len([item for item in os.listdir('output') if item.endswith('.pvec')])
    if output_count == 0:
        return {
            "result": "error",
            "message": "No pvec files were generated",
            "input_count": len(input_files),
            "des_count": des_count,
            "skipped": skipped[:50],
            "skipped_count": len(skipped),
            "output_count": 0,
        }, 500
    return {
        "result": "pvecs calculated",
        "function_type": function_type,
        "threads": threads,
        "input_count": len(input_files),
        "des_count": des_count,
        "output_count": output_count,
        "skipped": skipped[:50],
        "skipped_count": len(skipped),
    }

@app.route('/clearpvecs', methods=['GET'])
def clearpvecs():
    """
    docstring
    """
    def clearfolder(mydir):
        """
        docstring
        """
        #filelist = [ f for f in os.listdir(mydir)]
        for f in os.listdir(mydir):
            os.remove(os.path.join(mydir, f))
    clearfolder("input")
    clearfolder("output")
    clearfolder("des")
    clearfolder("pdg")
    return {"result": "pvecs cleared"}



@app.route('/getjson',methods=['GET'])
def requestjson():
    result = {}
    result['pvecs'] = {}
    for fname in os.listdir('output'):
        with open('output/' + fname) as f:
            lines = f.readlines()
            
        firstrow = lines[0].split()
        secondrow = lines[1].split()
        nname = fname.split(".")[0]
        result['pvecs'][nname] = {
            "distance": firstrow[0],
            "Sfactor": firstrow[1],
            "vector": secondrow
        }
    return result

@app.route('/download-zip')
def request_zip():
    

    # datetime object containing current date and time
    now = datetime.now()
    # dd/mm/YY H:M:S
    dt_string = now.strftime("%d/%m/%Y %H:%M:%S")
    data = io.BytesIO()
    with zipfile.ZipFile(data, mode='w') as z:
        for f_name in os.listdir('output'):
            z.write('output/' + f_name)
    data.seek(0)
    return send_file(
        data,
        mimetype='application/zip',
        as_attachment=True,
        cache_timeout=-1,
        attachment_filename='{}.zip'.format(dt_string)
    )

@app.route('/sendfile', methods=['GET', 'POST'])
def sendfile():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        # if user does not select file, browser also
        # submit an empty part without filename
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join('input', filename))
            return redirect(url_for('sendfile',
                                    filename=filename))
    return '''
    <!doctype html>
    <title>Upload new File</title>
    <h1>Upload new File</h1>
    <form method=post enctype=multipart/form-data>
      <input type=file name=file>
      <input type=submit value=Upload>
    </form>
    '''
