var activearchives
var loadcount
var ingestcount
var neur
var dm
//var serverbase = 'http://cngpro.gmu.edu:5000/'
var serverbase = '../'

$(document).ready(function() {
    activearchives = JSON.parse(getarchives());
    if (activearchives.status == 'error') {
        window.alert("Archive csv file mismatch!!!!");
        return;
    }
    $(document).on('click', '.dropdown-menu.keep-open', function(e) {
        e.stopPropagation();
    });
    createArchivePanel(activearchives.data);
    createDataPanel(activearchives.data)
});

function openAreLogWindow() {
    window.open(
        serverbase + 'ui/log.html',
        'areLogWindow',
        'width=900,height=650,resizable=yes,scrollbars=yes'
    );
}

function getarchives() {
    //get archives available - called on load
    dm = {};    
    return $.ajax({
        url: '../getarchives/',
        async: !1,
        error: function () {
            console.log(url);

            console.log("Error!");
        },
        success: function (result) {
            console.log(result);
            activearchives = result;			
        },
        type: 'GET'
    }).responseText;
}

function readarchives() {
    /* read available archives - on clicking "read archives"
        returns archives and their statuses.
    */

    var totalneurons = 0;
    activearchives.data.forEach(element => {
        totalneurons += element.nneurons;
    });
    loadcount = 0;
    abutton = document.getElementById("read_button");
    abutton.classList.add('disabled');
    activearchives.data.forEach(archive => {
        
        $.ajax({
        url: serverbase + 'readarchive/' + archive.name,
        error: function () {
            console.log("Error!");
        },
        success: function (result) {
            console.log(result)
            loadcount += archive.nneurons;
            part = loadcount/totalneurons*100;
            if (result.status == 'error') {
                abutton = document.getElementById(archive.name + "_button")
                abutton.classList.remove('btn-secondary')
                abutton.classList.add('btn-danger')
                abutton = document.getElementById("read_button")
                abutton.classList.add('enabled')
                          
            }
            else {
                abutton = document.getElementById(archive.name + "_button")
                abutton.classList.remove('btn-secondary')
                abutton.classList.add('btn-dark')
                

            }
            abuttontext = document.getElementById(archive.name + "_message")  
            abuttontext.innerHTML = result.message
            if (Math.round(part) == 100) { 
                
                activearchives = JSON.parse(getarchives());
                if (activearchives.status == 'error') {
                    window.alert("Archive csv-file mismatch!");
                    return;
                }
                abutton = document.getElementById("read_button");
                abutton.classList.remove('disabled');
                $(".container").empty()
                createDataPanel(activearchives.data)
                $(".archivecont").empty()
                createArchivePanel(activearchives.data)
                anelem = document.getElementById("archivebar")
                anelem.classList.remove('progress-bar-animated')
                anelem.classList.remove('progress-bar-striped')
            }
            abar = document.getElementById("archivebar");
            abar.style.width = (part).toString() + '%'; 			
        },
        type: 'GET'
        }); 
    });
}

function exportdatabases() {
    const progressWrapId = "export_db_progress_wrap";
    const progressId = "export_db_progress";
    const progressTextId = "export_db_progress_text";
    const resultId = "export_db_result";
    const selected = [];
    if (document.getElementById("export_mysql_review").checked) selected.push('mysql_review');
    if (document.getElementById("export_mysql_main").checked) selected.push('mysql_main');
    if (document.getElementById("export_postgres").checked) selected.push('postgres');

    if (selected.length === 0) {
        document.getElementById(progressTextId).textContent = "Select at least one database to export.";
        document.getElementById(progressId).className = "progress-bar bg-warning";
        document.getElementById(progressId).style.width = "100%";
        document.getElementById(progressId).textContent = "0%";
        return;
    }

    const exportButton = document.getElementById("export_db_button");
    const progressBar = document.getElementById(progressId);
    const progressText = document.getElementById(progressTextId);
    const resultBox = document.getElementById(resultId);
    document.getElementById(progressWrapId).style.display = "block";
    progressBar.className = "progress-bar progress-bar-striped progress-bar-animated bg-info";
    progressBar.style.width = "15%";
    progressBar.textContent = "15%";
    progressText.textContent = "Starting database export...";
    resultBox.innerHTML = "";
    exportButton.classList.add('disabled');
    exportButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Exporting DBs...';

    $.ajax({
        url: serverbase + 'exportdb/?' + selected.map(db => 'db=' + encodeURIComponent(db)).join('&'),
        type: 'GET',
        beforeSend: function () {
            progressBar.style.width = "45%";
            progressBar.textContent = "45%";
            progressText.textContent = "Exporting selected databases...";
        },
        error: function (xhr) {
            const message = xhr.responseJSON && xhr.responseJSON.message ? xhr.responseJSON.message : 'Unknown export error.';
            progressBar.className = "progress-bar bg-danger";
            progressBar.style.width = "100%";
            progressBar.textContent = "Failed";
            progressText.textContent = "Database export failed.";
            resultBox.innerHTML = `<div class="small text-danger mt-2">${message}</div>`;
            exportButton.classList.remove('disabled');
            exportButton.innerHTML = 'Run export';
        },
        success: function (result) {
            if (result.status === 'error') {
                progressBar.className = "progress-bar bg-danger";
                progressBar.style.width = "100%";
                progressBar.textContent = "Failed";
                progressText.textContent = "Database export failed.";
                resultBox.innerHTML = `<div class="small text-danger mt-2">${result.message}</div>`;
            } else {
                progressBar.className = "progress-bar bg-success";
                progressBar.style.width = "100%";
                progressBar.textContent = "100%";
                progressText.textContent = "Database export complete.";
                const lines = [];
                Object.keys(result.outputs || {}).forEach(key => {
                    lines.push(`<div class="small text-success mt-1"><strong>${key}</strong>: ${result.outputs[key]}</div>`);
                });
                resultBox.innerHTML = lines.join("");
            }
            exportButton.classList.remove('disabled');
            exportButton.innerHTML = 'Run export';
        }
    });
}

function importdatabase() {
    const target = document.getElementById("import_db_target").value;
    const fileInput = document.getElementById("import_db_file");
    const progressWrapId = "import_db_progress_wrap";
    const progressId = "import_db_progress";
    const progressTextId = "import_db_progress_text";
    const resultId = "import_db_result";
    const importButton = document.getElementById("import_db_button");
    const progressBar = document.getElementById(progressId);
    const progressText = document.getElementById(progressTextId);
    const resultBox = document.getElementById(resultId);

    if (!target) {
        document.getElementById(progressWrapId).style.display = "block";
        progressBar.className = "progress-bar bg-warning";
        progressBar.style.width = "100%";
        progressBar.textContent = "0%";
        progressText.textContent = "Select a database target.";
        resultBox.innerHTML = "";
        return;
    }

    if (!fileInput.files || fileInput.files.length === 0) {
        document.getElementById(progressWrapId).style.display = "block";
        progressBar.className = "progress-bar bg-warning";
        progressBar.style.width = "100%";
        progressBar.textContent = "0%";
        progressText.textContent = "Select a dump file to import.";
        resultBox.innerHTML = "";
        return;
    }

    const formData = new FormData();
    formData.append("db_target", target);
    formData.append("dump_file", fileInput.files[0]);

    document.getElementById(progressWrapId).style.display = "block";
    progressBar.className = "progress-bar progress-bar-striped progress-bar-animated bg-info";
    progressBar.style.width = "15%";
    progressBar.textContent = "15%";
    progressText.textContent = "Uploading dump file...";
    resultBox.innerHTML = "";
    importButton.classList.add("disabled");
    importButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Importing...';

    $.ajax({
        url: serverbase + 'importdb/',
        type: 'POST',
        data: formData,
        processData: false,
        contentType: false,
        xhr: function () {
            const xhr = new window.XMLHttpRequest();
            xhr.upload.addEventListener('progress', function (event) {
                if (event.lengthComputable) {
                    const uploadProgress = Math.max(15, Math.min(85, Math.round((event.loaded / event.total) * 70 + 15)));
                    progressBar.style.width = uploadProgress + "%";
                    progressBar.textContent = uploadProgress + "%";
                    progressText.textContent = "Uploading dump file...";
                }
            });
            return xhr;
        },
        beforeSend: function () {
            progressBar.style.width = "25%";
            progressBar.textContent = "25%";
            progressText.textContent = "Starting import...";
        },
        error: function (xhr) {
            const message = xhr.responseJSON && xhr.responseJSON.message ? xhr.responseJSON.message : 'Unknown import error.';
            progressBar.className = "progress-bar bg-danger";
            progressBar.style.width = "100%";
            progressBar.textContent = "Failed";
            progressText.textContent = "Database import failed.";
            resultBox.innerHTML = `<div class="small text-danger mt-2">${message}</div>`;
            importButton.classList.remove("disabled");
            importButton.innerHTML = "Run import";
        },
        success: function (result) {
            if (result.status === 'error') {
                progressBar.className = "progress-bar bg-danger";
                progressBar.style.width = "100%";
                progressBar.textContent = "Failed";
                progressText.textContent = "Database import failed.";
                resultBox.innerHTML = `<div class="small text-danger mt-2">${result.message}</div>`;
            } else {
                progressBar.className = "progress-bar bg-success";
                progressBar.style.width = "100%";
                progressBar.textContent = "100%";
                progressText.textContent = "Database import complete.";
                resultBox.innerHTML = `<div class="small text-success mt-2"><strong>${result.database}</strong> imported from ${result.filename}</div>`;
            }
            importButton.classList.remove("disabled");
            importButton.innerHTML = "Run import";
        }
    });
}

function exportarchivedata() {
    const archiveSelect = document.getElementById("export_archive_target");
    const archiveName = archiveSelect.value;
    const progressWrapId = "export_archive_progress_wrap";
    const progressId = "export_archive_progress";
    const progressTextId = "export_archive_progress_text";
    const resultId = "export_archive_result";
    const exportButton = document.getElementById("export_archive_button");
    const progressBar = document.getElementById(progressId);
    const progressText = document.getElementById(progressTextId);
    const resultBox = document.getElementById(resultId);

    if (!archiveName) {
        document.getElementById(progressWrapId).style.display = "block";
        progressBar.className = "progress-bar bg-warning";
        progressBar.style.width = "100%";
        progressBar.textContent = "0%";
        progressText.textContent = "Select an exported archive.";
        resultBox.innerHTML = "";
        return;
    }

    document.getElementById(progressWrapId).style.display = "block";
    progressBar.className = "progress-bar progress-bar-striped progress-bar-animated bg-info";
    progressBar.style.width = "20%";
    progressBar.textContent = "20%";
    progressText.textContent = "Preparing archive export bundle...";
    resultBox.innerHTML = "";
    exportButton.classList.add("disabled");
    exportButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Exporting...';

    $.ajax({
        url: serverbase + 'exportarchivedata/' + encodeURIComponent(archiveName),
        type: 'GET',
        beforeSend: function () {
            progressBar.style.width = "45%";
            progressBar.textContent = "45%";
            progressText.textContent = "Collecting files and JSP/XML updates...";
        },
        error: function (xhr) {
            const message = xhr.responseJSON && xhr.responseJSON.message ? xhr.responseJSON.message : 'Unknown archive export error.';
            progressBar.className = "progress-bar bg-danger";
            progressBar.style.width = "100%";
            progressBar.textContent = "Failed";
            progressText.textContent = "Archive data export failed.";
            resultBox.innerHTML = `<div class="small text-danger mt-2">${message}</div>`;
            exportButton.classList.remove("disabled");
            exportButton.innerHTML = "Ready";
        },
        success: function (result) {
            if (result.status === 'error') {
                progressBar.className = "progress-bar bg-danger";
                progressBar.style.width = "100%";
                progressBar.textContent = "Failed";
                progressText.textContent = "Archive data export failed.";
                resultBox.innerHTML = `<div class="small text-danger mt-2">${result.message}</div>`;
            } else {
                progressBar.className = "progress-bar bg-success";
                progressBar.style.width = "100%";
                progressBar.textContent = "100%";
                progressText.textContent = "Archive data export complete.";
                resultBox.innerHTML = `<div class="small text-success mt-2"><strong>${archiveName}</strong> bundle: ${result.bundle_root}</div>`;
            }
            exportButton.classList.remove("disabled");
            exportButton.innerHTML = "Ready";
        }
    });
}

function revertfrommain(archive_name) {
    const button = $('#' + archive_name + '_rfmbutton');
    button.prop('disabled', true).html(
        `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Reverting...`
    );

    $.ajax({
        url: serverbase + 'revertfrommain/' + archive_name,
        type: 'GET',
        error: function () {
            button.prop('disabled', false).html('Revert from main');
        },
        success: function (result) {
            if (result.status === 'error') {
                button.removeClass('btn-primary').addClass('btn-danger');
            } else {
                activearchives = JSON.parse(getarchives());
                $(".archivecont").empty();
                createArchivePanel(activearchives.data);
                $(".container").empty();
                createDataPanel(activearchives.data);
            }
        }
    });
}


function readarchive(archive_name) {
    /* read one archive - transform archive to button of reading.

    */

    /*
        reading status
    */
    const progressId = archive_name + '_read_progress';
    const progressWrapId = archive_name + '_read_progress_wrap';
    const progressTextId = archive_name + '_read_progress_text';

    $('#' + archive_name + '_button').prop('disabled', true)
    $('#' + archive_name + '_button').html(
        `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Reading archive...`
    );
    /*
        reading status
    */
    if (!document.getElementById(progressWrapId)) {
        $('#' + archive_name + '_button').closest('.btn-group').after(`
            <div id="${progressWrapId}" class="progress mt-2 mb-2" style="height: 20px;">
                <div id="${progressId}" class="progress-bar progress-bar-striped progress-bar-animated bg-info" role="progressbar" style="width: 0%">0%</div>
            </div>
            <div id="${progressTextId}" class="small text-muted mb-2">Starting archive read...</div>
        `);
    }
    const poller = setInterval(function () {
        $.ajax({
            url: serverbase + 'checkreadarchive/' + archive_name,
            type: 'GET',
            success: function (presult) {
                const progress = Math.max(0, Math.min(100, parseFloat(presult.progress || 0)));
                $('#' + progressId).css('width', progress + '%').text(Math.round(progress) + '%');
                $('#' + progressId).attr('aria-valuenow', progress);
                $('#' + progressTextId).text(presult.message || 'Reading archive...');

                if (presult.status === 'success' || presult.status === 'error') {
                    clearInterval(poller);
                    if (presult.status === 'success') {
                        $('#' + progressId).removeClass('progress-bar-animated progress-bar-striped bg-info').addClass('bg-success');
                        $('#' + progressTextId).text(presult.message || 'Archive read complete');
                    } else {
                        $('#' + progressId).removeClass('progress-bar-animated progress-bar-striped bg-info').addClass('bg-danger');
                        $('#' + progressTextId).text(presult.message || 'Archive read failed');
                    }
                }
            }
        });
    }, 1000);


    const readSteps = getReadSteps(archive_name);
    $.ajax({
    url: serverbase + 'readarchive_steps/' + archive_name,
    contentType: 'application/json',
    data: JSON.stringify({ steps: readSteps }),
    error: function () {
        console.log("Error!!!");
        alert("Read error: UNKNOW ERROR.");
    },
    success: function (result) {
        console.log(result)
        if (result.status == 'error') {
            alert("Read error: " + (result.message));
            abutton = document.getElementById(archive_name + "_button")
            abutton.classList.remove('btn-secondary')
            abutton.classList.add('btn-danger')
            abutton = document.getElementById("read_button")
            abutton.classList.add('enabled')                     
        }
        else {
            abutton = document.getElementById(archive_name + "_button")
            abutton.classList.remove('btn-secondary')
            abutton.classList.add('btn-dark')
            

        }
            
        activearchives = JSON.parse(getarchives());;
        if (activearchives.status == 'error') {
            window.alert("Archive csv-file mismatch!");
            return;
        }
        abutton = document.getElementById("read_button");
        abutton.classList.remove('disabled');
        $(".container").empty()
        createDataPanel(activearchives.data)
        $(".archivecont").empty()
        createArchivePanel(activearchives.data)		
    },
    type: 'POST'
    }); 
}

function getReadSteps(archive_name) {
    const stepNames = ['copy_files', 'source_files', 'precheck', 'pvec', 'duplicates', 'set_ready'];
    const steps = {};
    stepNames.forEach(function(stepName) {
        const element = document.getElementById(`${archive_name}_step_${stepName}`);
        steps[stepName] = !element || element.checked;
    });
    if (!steps.pvec) {
        steps.duplicates = false;
    }
    return steps;
}

function toggleReadStep(event, archive_name, stepName) {
    event.stopPropagation();
    if (stepName === 'pvec') {
        const duplicateElement = document.getElementById(`${archive_name}_step_duplicates`);
        if (duplicateElement && !event.target.checked) {
            duplicateElement.checked = false;
        }
    }
    if (stepName === 'duplicates' && event.target.checked) {
        const pvecElement = document.getElementById(`${archive_name}_step_pvec`);
        if (pvecElement) {
            pvecElement.checked = true;
        }
    }
}







function createArchivePanel(archives) {
    const exportableArchives = archives.filter(archive => ['public', 'published'].includes(archive.status));
    pcontent =
    `<div class="card" style ="overflow: visible !important;" >
        <div class="card-body" style ="overflow: visible !important;" >
        <h5 class="card-title">Available archives</h5>
        <div class="bd-example">`
    archives.forEach(archive => {
        switch (archive.status) {
            case 'ready':
                btnclass = 'btn-primary'
                break;
            case 'error':
                btnclass = 'btn-danger'
                break;
            case 'warning':
                btnclass = 'btn-warning'
                break;
            case 'partial':
                btnclass = 'btn-secondary'
                break;
            case 'read':
                btnclass = 'btn-info'
                break;
            case 'ingested':
                btnclass = 'btn-success'
                break;
            case 'published':
                btnclass = 'btn-light'
                break;
            default:
                btnclass = 'btn-primary'
                break;
        }
        parsedjson = ""
        if (archive.json.length > 0) {
            parsedjson += "<textarea>"
            archive.json.forEach(element => {
                parsedjson += `Original\t${element.Original}\tDuplicate\t${element.Duplicate}\n`
                
            });
            parsedjson += "</textarea>"
        }
        pcontent += `
        <div class="btn-group">
        <button id="${archive.name}_button" type="button" class="btn  ${btnclass} dropdown-toggle m-1" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">${archive.name} <span class="badge badge-light">${archive.nneurons}</span></button>
        <div class="dropdown-menu">
        <a class="dropdown-item" href="#" onclick="readarchive('${archive.name}')">Read archive</a>
        <div class="dropdown-divider"></div>
        <h6 class="dropdown-header">Read steps</h6>
        <label class="dropdown-item mb-0" onclick="event.stopPropagation();"><input type="checkbox" id="${archive.name}_step_copy_files" checked onchange="toggleReadStep(event, '${archive.name}', 'copy_files')"> Copy archive and metadata</label>
        <label class="dropdown-item mb-0" onclick="event.stopPropagation();"><input type="checkbox" id="${archive.name}_step_source_files" checked onchange="toggleReadStep(event, '${archive.name}', 'source_files')"> Source files and std logs</label>
        <label class="dropdown-item mb-0" onclick="event.stopPropagation();"><input type="checkbox" id="${archive.name}_step_precheck" checked onchange="toggleReadStep(event, '${archive.name}', 'precheck')"> Precheck files</label>
        <label class="dropdown-item mb-0" onclick="event.stopPropagation();"><input type="checkbox" id="${archive.name}_step_pvec" checked onchange="toggleReadStep(event, '${archive.name}', 'pvec')"> PVec</label>
        <label class="dropdown-item mb-0" onclick="event.stopPropagation();"><input type="checkbox" id="${archive.name}_step_duplicates" checked onchange="toggleReadStep(event, '${archive.name}', 'duplicates')"> Duplicate check</label>
        <label class="dropdown-item mb-0" onclick="event.stopPropagation();"><input type="checkbox" id="${archive.name}_step_set_ready" checked onchange="toggleReadStep(event, '${archive.name}', 'set_ready')"> Set ready status</label>
        <div class="dropdown-divider"></div>
        <a class="dropdown-item" style="word-wrap: break-word;  white-space: normal;" id="${archive.name}_message" href="#">Status:${archive.status}. Status message:${archive.message}</a>
        
        ${parsedjson}
        </div>
        </div>`;
    });
    pcontent += `</div>

       <p class="card-text"></p>
       <a id="read_button" href="#" class="btn btn-primary mr-2" onclick="readarchives()">Read all archives</a>
       <div class="btn-group">
         <button type="button" class="btn btn-secondary dropdown-toggle" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
           Export full DB
         </button>
         <div class="dropdown-menu keep-open p-3" style="min-width: 260px;">
           <div class="form-check">
             <input class="form-check-input" type="checkbox" id="export_mysql_review" checked>
             <label class="form-check-label" for="export_mysql_review">MySQL review (nmdbDev)</label>
           </div>
           <div class="form-check">
             <input class="form-check-input" type="checkbox" id="export_mysql_main" checked>
             <label class="form-check-label" for="export_mysql_main">MySQL main (NeuMO)</label>
           </div>
           <div class="form-check mb-3">
             <input class="form-check-input" type="checkbox" id="export_postgres" checked>
             <label class="form-check-label" for="export_postgres">Postgres (nmo)</label>
           </div>
           <button id="export_db_button" type="button" class="btn btn-secondary btn-sm btn-block" onclick="exportdatabases()">Run export</button>
           <div id="export_db_progress_wrap" class="progress mt-3" style="height: 18px; display: none;">
             <div id="export_db_progress" class="progress-bar progress-bar-striped progress-bar-animated bg-info" role="progressbar" style="width: 0%">0%</div>
           </div>
           <div id="export_db_progress_text" class="small text-muted mt-2"></div>
           <div id="export_db_result" class="mt-1"></div>
         </div>
       </div>
       <div class="btn-group ml-2">
         <button type="button" class="btn btn-secondary dropdown-toggle" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
           Import full DB
         </button>
         <div class="dropdown-menu keep-open p-3" style="min-width: 320px;">
           <div class="form-group mb-2">
             <label class="small mb-1" for="import_db_target">Database</label>
             <select id="import_db_target" class="form-control form-control-sm">
               <option value="">Select target</option>
               <option value="mysql_review">MySQL review (nmdbDev)</option>
               <option value="mysql_main">MySQL main (NeuMO)</option>
               <option value="logging_data">MySQL LoggingData</option>
               <option value="postgres">Postgres (nmo)</option>
             </select>
           </div>
           <div class="form-group mb-3">
             <label class="small mb-1" for="import_db_file">Dump file</label>
             <input id="import_db_file" type="file" class="form-control-file" accept=".sql">
           </div>
           <button id="import_db_button" type="button" class="btn btn-secondary btn-sm btn-block" onclick="importdatabase()">Run import</button>
           <div id="import_db_progress_wrap" class="progress mt-3" style="height: 18px; display: none;">
             <div id="import_db_progress" class="progress-bar progress-bar-striped progress-bar-animated bg-info" role="progressbar" style="width: 0%">0%</div>
           </div>
           <div id="import_db_progress_text" class="small text-muted mt-2"></div>
           <div id="import_db_result" class="mt-1"></div>
         </div>
       </div>
       <div class="btn-group ml-2">
         <button type="button" class="btn btn-secondary dropdown-toggle" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
           Export archive data
         </button>
         <div class="dropdown-menu keep-open p-3" style="min-width: 320px;">
           <div class="form-group mb-3">
             <label class="small mb-1" for="export_archive_target">Archive</label>
             <select id="export_archive_target" class="form-control form-control-sm">
               <option value="">Select exported archive</option>
               ${exportableArchives.map(archive => `<option value="${archive.name}">${archive.name}</option>`).join("")}
             </select>
           </div>
           <button id="export_archive_button" type="button" class="btn btn-secondary btn-sm btn-block" onclick="exportarchivedata()">Ready</button>
           <div id="export_archive_progress_wrap" class="progress mt-3" style="height: 18px; display: none;">
             <div id="export_archive_progress" class="progress-bar progress-bar-striped progress-bar-animated bg-info" role="progressbar" style="width: 0%">0%</div>
           </div>
           <div id="export_archive_progress_text" class="small text-muted mt-2"></div>
           <div id="export_archive_result" class="mt-1"></div>
         </div>
       </div>
       <button type="button" class="btn btn-outline-primary ml-2" id="logViewerOpenInline" onclick="openAreLogWindow()">Log</button>
    </div> <div class="progress">
    <div id='archivebar' class="progress-bar progress-bar-striped progress-bar-animated" role="progressbar" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100" style="width: 0%"></div>
  <br/>
    </div>`


    $(pcontent).appendTo(".archivecont");
}


function ingestneuron(archive,icount) {
    neuron = archive.neurons[icount];
    part = 1 / archive.neurons.length;

    console.log('Ingesting neuron: ' + neuron.neuron_name);
    if (neuron.status != "ingested" && neuron.status != "published") {
        $.ajax({
            url: serverbase + 'ingestneuron/' + neuron.neuron_name,
            error: function () {
                console.log("Error!");
            },
            type: 'GET',
            success: function(result) {
                $("#inglog").innerHTML = 
                abutton = document.getElementById(neuron.neuron_name + "_button");
                abutton.classList.remove('btn-secondary');
                if (result.status == 'error') {
                    abutton.classList.add('btn-danger');

                    abar = document.getElementById('cnt' + archive.name + 2)
                    abarwidth = parseFloat(abar.style.width.slice(0,-1)) + part * 100;
                    abar.style.width = (abarwidth).toString() + '%';
                }
                else {
                    abutton.classList.add('btn-success');

                    abar = document.getElementById('cnt' + archive.name + 3)
                    abarwidth = parseFloat(abar.style.width.slice(0,-1)) + part * 100;
                    abar.style.width = (abarwidth).toString() + '%';
                }
                readybar = document.getElementById('cnt' + archive.name + 1);
                readybarwidth = parseFloat(readybar.style.width.slice(0,-1))-part * 100;
                readybar.style.width = (readybarwidth).toString() + '%';
                
                abuttontext = document.getElementById(neuron.neuron_name  + "_message") ; 
                abuttontext.innerHTML = result.message;

                neuronlink = document.getElementById(neuron.neuron_name  + "_link") ;
                neuronlink.classList.remove('disabled');

                neuroningest = document.getElementById(neuron.neuron_name  + "_ingest") ;
                neuroningest.classList.add('disabled');
                
                anelem = document.getElementById(archive.name + "_button");
                anelem.classList.remove('btn-info');
                anelem.classList.add('btn-warning');

                console.log(Math.round(part))
                if (archive.neurons.length ==icount +1) {
                    console.log('Done!') 
                    console.log(archive.neurons.length)
                    anelem = document.getElementById('cnt' + archive.name + 1);
                    anelem.classList.remove('progress-bar-animated');
                    anelem.classList.remove('progress-bar-striped');
                    
                    anelem = document.getElementById('cnt' + archive.name + 2);
                    anelem.classList.remove('progress-bar-animated');
                    anelem.classList.remove('progress-bar-striped');
                    //readybarwidth = parseFloat(anelem.style.width.slice(0,-1))-part*100;
                    readybar.style.width = '0%';

                    anelem = document.getElementById('cnt' + archive.name + 3);
                    anelem.classList.remove('progress-bar-animated');
                    anelem.classList.remove('progress-bar-striped');

                    anelem = document.getElementById(archive.name + "_button");
                    anelem.classList.remove('btn-info');
                    anelem.classList.remove('btn-warning');
                    anelem.classList.add('btn-success');
                    activearchives = JSON.parse(getarchives());
                    if (activearchives.status == 'error') {
                        window.alert("Archive csv mismatch!");
                        return;
                    }
                    $(".archivecont").empty()
                    
                    createArchivePanel(activearchives.data);
                }
                else {
                    ingestneuron(archive,icount+1);
                    
                }   
            }
        });
    }
    else {
        ingestneuron(archive,icount+1);
    }    
}
    


function ingestwrap(neuron_name,archive_name) {
    activearchives = JSON.parse(getarchives()).data
    notFound = true;
    var anarchive; 
    ix = -1;
    while (notFound) {
        ix++
        notFound = activearchives[ix].name != archive_name;
    }
    archive = activearchives[ix]

    part = 1 / archive.neurons.length;
    console.log('Ingesting neuron: ' + neuron_name);
    $.ajax({
        url: serverbase + 'ingestneuron/' + neuron_name,
        error: function () {
            console.log("Error!");
        },
        type: 'GET',
        success: function(result) {
            abutton = document.getElementById(neuron_name+ "_button");
            abutton.classList.remove('btn-secondary');
            if (result.status == 'error') {
                abutton.classList.add('btn-danger');

                abar = document.getElementById('cnt' + archive.name + 2)
                abarwidth = parseFloat(abar.style.width.slice(0,-1)) + part * 100;
                abar.style.width = (abarwidth).toString() + '%';
            }
            else {
                abutton.classList.add('btn-success');

                abar = document.getElementById('cnt' + archive.name + 3)
                abarwidth = parseFloat(abar.style.width.slice(0,-1)) + part * 100;
                abar.style.width = (abarwidth).toString() + '%';
            }
            readybar = document.getElementById('cnt' + archive.name + 1);
            readybarwidth = parseFloat(readybar.style.width.slice(0,-1))-part * 100;
            readybar.style.width = (readybarwidth).toString() + '%';
            
            abuttontext = document.getElementById(neuron_name + "_message") ; 
            abuttontext.innerHTML = result.message;

            neuronlink = document.getElementById(neuron_name + "_link") ;
            neuronlink.classList.remove('disabled');

            neuroningest = document.getElementById(neuron_name  + "_ingest") ;
            neuroningest.classList.add('disabled');
            
            anelem = document.getElementById(archive.name + "_button");
            anelem.classList.remove('btn-info');
            anelem.classList.add('btn-warning');
 
        }
    })
    
}

function getanarchive(archive_name) {
    activearchives = JSON.parse(getarchives()).data
    notFound = true;
    var anarchive; 
    ix = -1;
    while (notFound) {
        ix++
        notFound = activearchives[ix].name != archive_name;
    }
    return activearchives[ix];
    
}
function ingestallneurons(archive_name) {
    $('#' + archive_name + '_ibutton').prop('disabled', true)
    $('#' + archive_name + '_ibutton').html(
        `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Ingesting archive...`
    );
    $.ajax({
		url: serverbase + 'ingestarchive/' + archive_name,
		error: function () {
			console.log("Error!");
		},
		success: function (result) {
            console.log(result)
            if (result['status'] == 'success') {
                $('#' + archive_name + '_ibutton').html(
                    `Ingested successfully to review`
                );	
                
            } else {
                $('#' + archive_name + '_ibutton').html(
                    `Ingestion failed`
                );	
                
            }
            
		},
		type: 'GET'
    });

    // nData = dictArchiveNeuron["archive"];
    /*
    anarchive = getanarchive(archive_name);

    
    anelem = document.getElementById('cnt' + archive_name + 1);
    anelem.classList.add('progress-bar-animated');
    anelem.classList.add('progress-bar-striped');
    anelem = document.getElementById('cnt' + archive_name + 2);
    anelem.classList.add('progress-bar-animated');
    anelem.classList.add('progress-bar-striped');
    anelem = document.getElementById('cnt' + archive_name + 3);
    anelem.classList.add('progress-bar-animated');
    anelem.classList.add('progress-bar-striped');
    //ingestneuron(anarchive,0);*/
}

function revertallneurons(archive_name) {
    $.ajax({
		url: serverbase + 'revertarchive/' + archive_name,
		error: function () {
			console.log("Error!");
		},
		success: function (result) {
            console.log(result)
            activearchives = JSON.parse(getarchives());
            if (activearchives.status == 'error') {
                window.alert("Archive csv-file mismatch!");
                return;
            }
            $(".archive_rbuttoncont").empty().innerHTML = ""
            $(".container").empty().innerHTML = ""
            
            createArchivePanel(activearchives.data)
            createDataPanel(activearchives.data)			
		},
		type: 'GET'
    }); 
    
}

function deleteneuronmodal(neuronname,archive) {
    $('#deleteneuronmodal').modal('show');
    $('#deleteneuronmodal').on('shown.bs.modal', function (e) {
        $('#deleteneuronmodal').find('.modal-body').html(
            `Are you sure you want to delete the neuron <b>${neuronname}</b> from the archive <b>${archive}</b>?`
        );
        $('#deleteneuronmodal').find('.modal-footer').html(
            `<button type="button" class="btn btn-secondary" data-dismiss="modal">Close</button>
            <button type="button" class="btn btn-danger" data-dismiss="modal" onclick="deleteneuron('${neuronname}','${archive}')">Delete</button>`
        );
    });
}

function deleteneuron(neuronname,archive) {
    $.ajax({
		url: serverbase + 'deleteneuron/' + neuronname,
		error: function () {
			console.log("Error!");
		},
		success: function (result) {
            console.log("Error!");
            console.log(result)
            
            var elem = document.getElementById(neuronname + '_button');
            elem.parentNode.removeChild(elem);
            			
		},
		type: 'GET'
    }); 
    
}

function tweetneuron(neuronname,archive) {
    $.ajax({
		url: serverbase + 'tweetneuron/' + neuronname + '/' + archive + '/',
		error: function () {
			console.log("Error!");
            alert('Tweet error.');
		},
		success: function (result) {
            console.log(result)
            alert('Tweet successfully for ' + neuronname + " and embeded!");
            
            var elem = document.getElementById(neuronname + '_tweet');
            elem.className = "dropdown-item active";
            			
		},
		type: 'GET'
    }); 
    
}



function genwinjsp(archive_name) {
    $('#' + archive_name + '_wbutton').prop('disabled', true)
    $.ajax({
		url: serverbase + 'genwinjsp/' + archive_name,
		error: function () {
			console.log("Error!");
		},
		success: function (result) {
            console.log(result)		
		},
		type: 'GET'
    }); 
}

function exporttomain(archive_name) {
    $('#' + archive_name + '_mbutton').prop('disabled', true)
    $('#' + archive_name + '_mbutton').html(
        `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Exporting to main...`
    );
    $.ajax({
		url: serverbase + 'exporttomain/' + archive_name,
		error: function () {
			console.log("Error!");
		},
		success: function (result) {
            console.log(result)
            if (result['status'] == 'success') {
                $('#' + archive_name + '_mbutton').html(
                    `Exported successfully to main`
                );	
                
            } else {
                $('#' + archive_name + '_mbutton').html(
                    `Exported to main failed`
                );	
                
            }
            
		},
		type: 'GET'
    }); 
}


function createDataPanel(archives){
    
    //dictArchiveNeuron = createArchiveNeuronDict(count, ingestioData);
    //dictArchiveCount = createArchiveCountDict(count, ingestioData);
    //keyCount = 0;
    //dictArchiveNeuron = sortOnKeys(dictArchiveNeuron);
    archives.forEach(archive => {
        var statarr = [0,0,0,0];
        var total = 0
        archive.neurons.forEach(neuron => {
            total++;
            switch (neuron.status) {
                case "error":
                    statarr[1]++;
                    break;
                case "read":
                    statarr[0]++;
                    break;
                case "ingested":
                    statarr[2]++;
                    break;
                case "public":
                    statarr[3]++;
                    break;
                default:
                    break;
            }
        });
        if (total == 0) {
            total++
        } 
        
 //       for (var index = 0; index < neuronData.length; index++) {
   //         if (index == 0){
    
        if (["error", "ingested", "ready"].includes(archive.status)) {
            idisabled = 'disabled="true"'
        }
        else {
            idisabled = ""
        }

        if (["ready"].includes(archive.status)) {
            rdisabled = 'disabled="true"'
        }
        else {
            rdisabled = ""
        }
        
        var elm = 
        `<div class="progress">
        <div id="cnt${archive.name + 1}" class="progress-bar " role="progressbar" style="width:${statarr[0]/total*100}%;  background-color:grey">Read</div>
        <div id="cnt${archive.name + 2}" class="progress-bar bg-danger" role="progressbar" style="width:${statarr[1]/total*100}%;  background-color:grey">Error</div>
        <div id="cnt${archive.name + 3}" class="progress-bar bg-success" role="progressbar" style="width:${statarr[2]/total*100}%;  background-color:grey">Ingested</div>
        <div id="cnt${archive.name + 4}" class="progress-bar bg-info" role="progressbar" style="width:${statarr[3]/total*100}%;  background-color:grey">Published</div>
        </div>
        <div class="card" style="overflow: visible">
        <div class="card-header">
        <table class="table table-active" width="100%">
        <tr>
        <td width="150px">
        <a data-toggle="collapse" href="#collapse${archive.name}"  class="" aria-expanded="true">${archive.name}</a>
        </td>
        <td> Link: <a target="_blank" href="${archive.link}">to archive&gt;&gt;</a></td> 
        
        <td><button id="${archive}button" type="button" class="btn btn-primary dropdown-toggle m-1" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">Twitter <br/> neuron</button>
        <div class="dropdown-menu p-4" style="white-space: normal; overflow: visible">`
       
        archive.neurons.forEach(neuron => {
            elm +=`<button id="${neuron.neuron_name}_tweet" class="dropdown-item" onclick="tweetneuron('${neuron.neuron_name}','${neuron.archive}')" type="button">${neuron.neuron_name}</button>
            `;
        });

        elm +=`

        </div>
        </div></td>
        
        <td><button id="${archive.name}_ibutton" ${idisabled} class="btn btn-primary btn-sm" type="button" style="float:right" onclick="ingestallneurons('${archive.name}',dm)">Ingest Archive</button></td>
        <td><button id="${archive.name}_wbutton" class="btn btn-primary btn-sm" type="button" style="float:right" onclick="genwinjsp('${archive.name}')">Publish WIN.jsp</button></td>
        <td><button id="${archive.name}_mbutton" class="btn btn-primary btn-sm" type="button" style="float:right" onclick="exporttomain('${archive.name}')">Export to main</button></td>
        <td><button id="${archive.name}_rbutton" ${rdisabled}  class="btn btn-primary btn-sm" type="button" style="float:right" onclick="deleteneurons('${archive.name}',dm)">Revert Archive</button></td>
        <td><button id="${archive.name}_arbutton" ${rdisabled}  class="btn btn-primary btn-sm" type="button" style="float:right" onclick="archiveneurons('${archive.name}',dm)">Archive neurons</button></td>
        <td><button id="${archive.name}_rfmbutton" ${archive.status === 'public' || archive.status === 'published' ? '' : 'disabled="true"'} class="btn btn-warning btn-sm" type="button" style="float:right" onclick="revertfrommain('${archive.name}')">Revert from main</button></td>
        <!-- <td><button id="${archive.name}_dbutton" ${rdisabled}  class="btn btn-primary btn-sm" type="button" style="float:right" onclick="archiveneurons('${archive.name}',dm)">Diameter Check</button></td> -->
        
        </tr>
        </table>
        </div>
        <div id="collapse${archive.name}" class="panel-collapse collapse" style="">
        <div class="card-body" style="overflow: visible">
        <ul class="list-group" id="group_${archive.name}" >
        <li class="list-group-item">`;

        archive.neurons.forEach(neuron => {
            switch (neuron.status) {
                case 'read':
                    btnclass = 'btn-secondary'
                    idisabled = "" 
                    ldisabled = "disabled"
                    ddisabled = ""
                    break;
                case 'error':
                    btnclass = 'btn-danger'
                    idisabled = ""
                    ldisabled = "disabled"
                    ddisabled = ""
                    break;
                case 'warning':
                    btnclass = 'btn-warning'
                    idisabled = ""
                    ldisabled = "disabled"
                    ddisabled = ""
                    break;
                case 'ingested':
                    btnclass = 'btn-success'
                    idisabled = "disabled"
                    ldisabled = ""
                    ddisabled = "disabled"
                    break;
                case 'public':
                    btnclass = 'btn-light'
                    idisabled = "disabled"
                    ldisabled = ""
                    ddisabled = "disabled"
                    break;
                default:
                    btnclass = 'btn-secondary'
                    idisabled = ""
                    ldisabled = "disabled"
                    ddisabled = ""
                    break;
            }
            elm += `
            <div class="btn-group">
            <button id="${neuron.neuron_name}_button" type="button" class="btn ${btnclass} dropdown-toggle m-1" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">${neuron.neuron_name}</button>
            <div class="dropdown-menu dropdown-menu-center p-4" style="white-space: normal;">
            <button id="${neuron.neuron_name}_ingest"  class="dropdown-item ${idisabled}" onclick="ingestwrap('${neuron.neuron_name}','${neuron.archive}')" type="button">Ingest neuron</button>
            <a target="_blank" id="${neuron.neuron_name}_link" class="dropdown-item ${ldisabled}" href="http://cng.gmu.edu:8080/neuroMorphoReview/neuron_info.jsp?neuron_name=${neuron.neuron_name}" >Neuron link </a>
            <button id="${neuron.neuron_name}_delete"  class="dropdown-item ${ddisabled}" onclick="deleteneuronmodal('${neuron.neuron_name}','${neuron.archive}')" type="button">Delete neuron</button>
            <div class="dropdown-divider"></div>
            <h6 class="dropdown-header">Status</h6>
            <p class="dropdown-item disabled" id="${neuron.neuron_name}_message">
                ${neuron.message}
            </p>
            </div>
            </div>
            `;
        });
        elm += 
        `
        </li>
        </ul>
        </div>
        </div>`

        $(elm).appendTo(".container");

            
    });
}

function deleteneurons(archive) {
    //Send json request with all neurons to delete

    $('#' + archive + '_rbutton').prop('disabled', true)
            $('#' + archive + '_rbutton').html(
            `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Reverting archive...`); 
    var x = document.getElementById(archive + '_rbutton').parentElement;
    $(('#' + archive + '_rbutton')).hide().show(0)


    
    anarchive = getanarchive(archive);
    let xhr = new XMLHttpRequest();
    let url = serverbase + 'deleteneurons';

    // open a connection
    xhr.open("POST", url, true);

    // Set the request header i.e. which type of content you are sending
    xhr.setRequestHeader("Content-Type", "application/json");

    // Create a state change callback
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4) {

            // Print received data from server
            console.log(this.responseText);
            $('#' + archive + '_rbutton').html(
            `Archive reverted`);
            setTimeout(() => {  
                activearchives = JSON.parse(getarchives());
                if (activearchives.status == 'error') {
                    window.alert("Archive csv-file mismatch!");
                    return;
                }
                $(".archivecont").empty()
                $(".container").empty().innerHTML = ""
                createArchivePanel(activearchives.data);
                createDataPanel(activearchives.data);	
            }, 500);

        }
    };

    // Converting JSON data to string
    var data = JSON.stringify(anarchive);

    // Sending data with the request
    console.log(xhr.send(data));
    

}

function archiveneurons(archive) {
    //Send json request with all neurons to delete

    $('#' + archive + '_arbutton').prop('disabled', true)
            $('#' + archive + '_arbutton').html(
            `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Archiving...`); 
    var x = document.getElementById(archive + '_arbutton').parentElement;
    $(('#' + archive + '_arbutton')).hide().show(0)


    
    anarchive = getanarchive(archive);
    let xhr = new XMLHttpRequest();
    let url = serverbase + 'archiveneurons';

    // open a connection
    xhr.open("POST", url, true);

    // Set the request header i.e. which type of content you are sending
    xhr.setRequestHeader("Content-Type", "application/json");

    // Create a state change callback
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4) {

            // Print received data from server
            console.log(this.responseText);
            $('#' + archive + '_arbutton').html(
            `Neurons archived`);
            setTimeout(() => {  
                activearchives = JSON.parse(getarchives());
                if (activearchives.status == 'error') {
                    window.alert("Archive csv-file mismatch!");
                    return;
                }
                $(".archivecont").empty()
                $(".container").empty().innerHTML = ""
                createArchivePanel(activearchives.data);
                createDataPanel(activearchives.data);	
            }, 500);

        }
    };

    // Converting JSON data to string
    var data = JSON.stringify(anarchive);

    // Sending data with the request
    console.log(xhr.send(data));
    

}

function getmessage(message) {
    if (message === null) {
        return ""
    }
    else {
        return message
    }
    
}


function getIngest(status) {
    if (status == 2 || status == 5) {
        return '';
    }
    else {
        return 'disabled="true"';
    }
}

function getDisabled(status,pos) {
    if (status == pos) {
        return '';
    }
    else {
        return 'disabled="true"';
    }
}

$('#start_button').on('click', function () {

	var iterations = 100000;

	progressbar.progress_max = iterations;


    var i = 0;
        
    (function loop() {

        i++;
        if (iterations % i === 100) {
    	    progressbar.set(i); //only updates the progressbar         
        }   
        
        if (i < iterations) {
            setTimeout(loop, 0);
        }
        
    })();

});
