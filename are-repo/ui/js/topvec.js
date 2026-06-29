var serverbase = '../'
var selectedSwcFiles = null;
var selectedSwcFolderName = '';

function toWslPath(p) {
    p = p.trim();
    var m = p.match(/^([A-Za-z]):[\\\/](.*)/);
    if (m) {
        var drive = m[1].toLowerCase();
        var rest = m[2].replace(/\\/g, '/');
        return '/mnt/' + drive + '/' + rest;
    }
    return p;
}

function setFolderFromPicker(input, targetId) {
    if (!input.files || input.files.length === 0) {
        return;
    }
    var firstFile = input.files[0];
    var relativePath = firstFile.webkitRelativePath || firstFile.name || '';
    var folder = relativePath.split('/')[0] || '';
    if (folder) {
        document.getElementById(targetId).value = toWslPath(folder);
    }
    if (targetId === 'swcdir') {
        selectedSwcFiles = input.files;
        selectedSwcFolderName = folder || 'selected_swc_folder';
    }
}

function topvecStart() {
    var swcdir = toWslPath(document.getElementById('swcdir').value.trim());
    var outputdir = toWslPath(document.getElementById('outputdir').value.trim());
    document.getElementById('swcdir').value = swcdir;
    document.getElementById('outputdir').value = outputdir;
    var threads = parseInt(document.getElementById('threads').value, 10);
    var statusDiv = document.getElementById('topvec_status');
    var progressWrap = document.getElementById('topvec_progress_wrap');
    var pbar = document.getElementById('topvec_pbar');
    var progressText = document.getElementById('topvec_progress_text');

    if (!swcdir || !outputdir) {
        statusDiv.innerHTML = '<div class="alert alert-warning">Please fill in both folder paths.</div>';
        return;
    }
    if (!threads || threads < 1 || threads > 32) {
        statusDiv.innerHTML = '<div class="alert alert-warning">Threads must be between 1 and 32.</div>';
        return;
    }

    document.getElementById('topvec_btn').disabled = true;
    statusDiv.innerHTML = '<div class="alert alert-info">Starting pvec generation with ' + threads + ' thread(s)...</div>';
    progressWrap.style.display = 'flex';
    pbar.style.width = '0%';
    pbar.classList.remove('bg-danger');
    pbar.classList.add('progress-bar-animated', 'progress-bar-striped', 'bg-success');
    progressText.textContent = '';

    if (selectedSwcFiles && selectedSwcFiles.length > 0 && swcdir === selectedSwcFolderName) {
        uploadSwcFolder(selectedSwcFiles, selectedSwcFolderName, function(uploadedDir) {
            startTopvecJob(uploadedDir, outputdir, threads);
        }, function(message) {
            statusDiv.innerHTML = '<div class="alert alert-danger">Error: ' + message + '</div>';
            document.getElementById('topvec_btn').disabled = false;
        });
        return;
    }
    startTopvecJob(swcdir, outputdir, threads);
}

function uploadSwcFolder(files, folderName, onSuccess, onError) {
    var formData = new FormData();
    formData.append('folder_name', folderName);
    for (var i = 0; i < files.length; i++) {
        if ((files[i].name || '').toLowerCase().endsWith('.swc')) {
            formData.append('files', files[i], files[i].name);
        }
    }

    $.ajax({
        url: serverbase + 'upload_swc_folder',
        type: 'POST',
        data: formData,
        processData: false,
        contentType: false,
        success: function(data) {
            if (data.status === 'error') {
                onError(data.message || 'Upload failed');
                return;
            }
            onSuccess(data.swcdir);
        },
        error: function() {
            onError('Upload failed. Check server logs.');
        }
    });
}

function startTopvecJob(swcdir, outputdir, threads) {
    var statusDiv = document.getElementById('topvec_status');
    $.ajax({
        url: serverbase + 'pvec_folder',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ swcdir: swcdir, outputdir: outputdir, threads: threads }),
        success: function(data) {
            if (data.status === 'error') {
                statusDiv.innerHTML = '<div class="alert alert-danger">Error: ' + data.message + '</div>';
                document.getElementById('topvec_btn').disabled = false;
                return;
            }
            statusDiv.innerHTML = '<div class="alert alert-info">Running... job: <strong>' + data.job_id + '</strong></div>';
            setTimeout(function() { topvecPoll(data.job_id); }, 1000);
        },
        error: function() {
            statusDiv.innerHTML = '<div class="alert alert-danger">Request failed. Check server logs.</div>';
            document.getElementById('topvec_btn').disabled = false;
        }
    });
}

function topvecPoll(job_id) {
    var statusDiv = document.getElementById('topvec_status');
    var pbar = document.getElementById('topvec_pbar');
    var progressText = document.getElementById('topvec_progress_text');

    $.get(serverbase + 'checkpvec/' + encodeURIComponent(job_id), function(data) {
        var pct = Math.round(data.progress || 0);
        pbar.style.width = pct + '%';
        pbar.setAttribute('aria-valuenow', pct);

        if (data.total > 0) {
            progressText.textContent = (data.message || 'Generating pvecs') + ' - ' + data.current + ' / ' + data.total;
        } else {
            progressText.textContent = data.message || (pct + '%');
        }

        if (data.status === 'error') {
            statusDiv.innerHTML = '<div class="alert alert-danger">Error generating pvecs. Check server logs.</div>';
            pbar.classList.remove('progress-bar-animated', 'progress-bar-striped', 'bg-success');
            pbar.classList.add('bg-danger');
            document.getElementById('topvec_btn').disabled = false;
        } else if (data.status === 'success' || pct >= 100) {
            statusDiv.innerHTML = '<div class="alert alert-success">Done! PVecs saved to: <code>' + document.getElementById('outputdir').value.trim() + '</code></div>';
            pbar.classList.remove('progress-bar-animated', 'progress-bar-striped');
            progressText.textContent = '100%';
            document.getElementById('topvec_btn').disabled = false;
        } else {
            setTimeout(function() { topvecPoll(job_id); }, 2000);
        }
    }).fail(function() {
        setTimeout(function() { topvecPoll(job_id); }, 5000);
    });
}
