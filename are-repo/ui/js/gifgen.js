//var serverbase = 'https://neuronmorpho.org/ingestapi/';
//var serverbase = 'http://cngpro.gmu.edu:5000/';
var serverbase = '../'

$(document).ready(function() {
    getarchives()
    ;
});

function getarchives(){
    $.get(serverbase + "getarchives/", function(data, status){
        console.log(data)
        genbuttonlist(data)
    });
}

function gifgen(archive) {
    setTimeout(checkstatus, 3000,archive);
    $.get(serverbase + "gifgen/" + archive, function(data, status){
        if (status == "success") {
            updateprogress(archive,100);


        }

    });
}

function checkstatus(archive) {
    /* Checks status of ingestion for archive.
    */

    $.get(serverbase + "checkgif/" + archive, function(data, status){
        console.log(status)
        if (status == "success") {
            updateprogress(archive,data.progress);
            if (data.status == "error"  ) {
                alert("Error genarating gifs for archive: " + archive)
            }
            else {
                if (data.progress == 100) {
                    //alert(archive + ": gifs generated.")
                }
                else {
                    setTimeout(checkstatus, 3000,archive);
                }
            }
        }
    });
}


function updateprogress(archive,percent) {
    pbar = document.getElementById("pbar_" + archive);
    //thewidth = parseFloat(pbar.style.width.slice(0,-1)) + 10;
    pbar.style.width = (percent).toString() + '%';
}

function genbuttonlist(data) {
    elem = `<table width="100%">`;
    data.data.forEach(element => {
        elem += `<tr>
            <td width=150><button type="button" class="btn btn-primary" onclick="gifgen('${element.name}')">${element.name}</button></td>
            <td><div class="progress">
            <div id='pbar_${element.name}' class="progress-bar bg-success" style="width: 0%" role="progressbar" aria-valuenow="10" aria-valuemin="0" aria-valuemax="100"></div>
            </div>
            </td>
        </tr>`
        checkstatus(element.name);
    });
    elem += "</table>";
    $(elem).appendTo(".test1");

}

function gifgenFolder() {
    var swcdir = document.getElementById('swcdir').value.trim();
    var outputdir = document.getElementById('outputdir').value.trim();
    var statusDiv = document.getElementById('gifgen_folder_status');
    var progressWrap = document.getElementById('gifgen_folder_progress_wrap');
    var pbar = document.getElementById('gifgen_folder_pbar');

    if (!swcdir || !outputdir) {
        statusDiv.innerHTML = '<span class="text-danger">Please fill in both folder paths.</span>';
        return;
    }

    document.getElementById('gifgen_folder_btn').disabled = true;
    statusDiv.innerHTML = '<span class="text-info">Starting GIF generation...</span>';
    progressWrap.style.display = 'flex';
    pbar.style.width = '0%';

    $.ajax({
        url: serverbase + 'gifgen_folder',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ swcdir: swcdir, outputdir: outputdir }),
        success: function(data) {
            if (data.status === 'error') {
                statusDiv.innerHTML = '<span class="text-danger">Error: ' + data.message + '</span>';
                document.getElementById('gifgen_folder_btn').disabled = false;
                return;
            }
            statusDiv.innerHTML = '<span class="text-info">Running... (job: ' + data.job_id + ')</span>';
            setTimeout(function() { checkFolderStatus(data.job_id); }, 3000);
        },
        error: function() {
            statusDiv.innerHTML = '<span class="text-danger">Request failed.</span>';
            document.getElementById('gifgen_folder_btn').disabled = false;
        }
    });
}

function checkFolderStatus(job_id) {
    var statusDiv = document.getElementById('gifgen_folder_status');
    var pbar = document.getElementById('gifgen_folder_pbar');

    $.get(serverbase + 'checkgif/' + job_id, function(data) {
        pbar.style.width = data.progress + '%';
        if (data.status === 'error') {
            statusDiv.innerHTML = '<span class="text-danger">Error generating GIFs.</span>';
            document.getElementById('gifgen_folder_btn').disabled = false;
        } else if (data.progress >= 100) {
            statusDiv.innerHTML = '<span class="text-success">Done! GIFs saved to output folder.</span>';
            pbar.classList.remove('progress-bar-animated', 'progress-bar-striped');
            document.getElementById('gifgen_folder_btn').disabled = false;
        } else {
            setTimeout(function() { checkFolderStatus(job_id); }, 3000);
        }
    });
}
