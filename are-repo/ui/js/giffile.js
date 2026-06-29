var serverbase = '../'
var selectedSwcFiles = null;
var selectedSwcFolderName = '';
var currentGiffileJobId = null;

function toWslPath(p) {
    p = p.trim();
    // C:\Users\... or C:/Users/...
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

function setGiffileButtons(disabled) {
    document.getElementById('giffile_btn').disabled = disabled;
    document.getElementById('giffile_resume_btn').disabled = disabled;
}

function setGiffileStopButton(enabled) {
    document.getElementById('giffile_stop_btn').disabled = !enabled;
}

function giffileStart(resume) {
    var swcdir = toWslPath(document.getElementById('swcdir').value.trim());
    var outputdir = toWslPath(document.getElementById('outputdir').value.trim());
    document.getElementById('swcdir').value = swcdir;
    document.getElementById('outputdir').value = outputdir;
    var threads = parseInt(document.getElementById('threads').value, 10);
    var statusDiv = document.getElementById('giffile_status');
    var progressWrap = document.getElementById('giffile_progress_wrap');
    var pbar = document.getElementById('giffile_pbar');
    var progressText = document.getElementById('giffile_progress_text');
    var logBox = document.getElementById('giffile_log');

    if (!swcdir || !outputdir) {
        statusDiv.innerHTML = '<div class="alert alert-warning">Please fill in both folder paths.</div>';
        return;
    }
    if (!threads || threads < 1 || threads > 32) {
        statusDiv.innerHTML = '<div class="alert alert-warning">Threads must be between 1 and 32.</div>';
        return;
    }

    setGiffileButtons(true);
    setGiffileStopButton(false);
    currentGiffileJobId = null;
    statusDiv.innerHTML = '<div class="alert alert-info">' + (resume ? 'Resuming' : 'Starting') + ' GIF generation with ' + threads + ' thread(s)...</div>';
    progressWrap.style.display = 'flex';
    pbar.style.width = '0%';
    pbar.textContent = '0%';
    pbar.classList.add('progress-bar-animated', 'progress-bar-striped');
    progressText.textContent = '';
    logBox.textContent = '';
    logBox.style.display = 'block';

    if (selectedSwcFiles && selectedSwcFiles.length > 0 && swcdir === selectedSwcFolderName) {
        uploadSwcFolder(selectedSwcFiles, selectedSwcFolderName, function(uploadedDir) {
            startGifJob(uploadedDir, outputdir, threads, resume);
        }, function(message) {
            statusDiv.innerHTML = '<div class="alert alert-danger">Error: ' + message + '</div>';
            setGiffileButtons(false);
        });
        return;
    }
    startGifJob(swcdir, outputdir, threads, resume);
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

function startGifJob(swcdir, outputdir, threads, resume) {
    var statusDiv = document.getElementById('giffile_status');
    $.ajax({
        url: serverbase + 'gifgen_folder',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ swcdir: swcdir, outputdir: outputdir, threads: threads, resume: !!resume }),
        success: function(data) {
            if (data.status === 'error') {
                statusDiv.innerHTML = '<div class="alert alert-danger">Error: ' + data.message + '</div>';
                setGiffileButtons(false);
                return;
            }
            currentGiffileJobId = data.job_id;
            setGiffileStopButton(true);
            statusDiv.innerHTML = '<div class="alert alert-info">' + (resume ? 'Resuming' : 'Running') + '... job: <strong>' + data.job_id + '</strong></div>';
            setTimeout(function() { giffilePoll(data.job_id); }, 3000);
        },
        error: function() {
            statusDiv.innerHTML = '<div class="alert alert-danger">Request failed. Check server logs.</div>';
            setGiffileButtons(false);
        }
    });
}

function giffileStop() {
    var statusDiv = document.getElementById('giffile_status');
    if (!currentGiffileJobId) {
        return;
    }
    setGiffileStopButton(false);
    statusDiv.innerHTML = '<div class="alert alert-warning">Stop requested. Finishing current work before stopping...</div>';
    $.ajax({
        url: serverbase + 'stopgif/' + encodeURIComponent(currentGiffileJobId),
        type: 'POST',
        success: function() {
            giffilePoll(currentGiffileJobId);
        },
        error: function() {
            statusDiv.innerHTML = '<div class="alert alert-danger">Stop request failed. Check server logs.</div>';
            setGiffileStopButton(true);
        }
    });
}

function giffilePoll(job_id) {
    var statusDiv = document.getElementById('giffile_status');
    var pbar = document.getElementById('giffile_pbar');
    var progressText = document.getElementById('giffile_progress_text');
    var logBox = document.getElementById('giffile_log');

    $.get(serverbase + 'checkgif/' + encodeURIComponent(job_id), function(data) {
        var pct = Math.round(data.progress || 0);
        pbar.style.width = pct + '%';
        pbar.textContent = pct + '%';
        pbar.setAttribute('aria-valuenow', pct);
        if (data.total > 0) {
            progressText.textContent = data.current + ' / ' + data.total;
        } else {
            progressText.textContent = pct + '%';
        }
        if (data.message) {
            progressText.textContent += ' - ' + data.message;
        }
        if (data.log && data.log.length > 0) {
            logBox.style.display = 'block';
            logBox.textContent = data.log.join('\n');
            logBox.scrollTop = logBox.scrollHeight;
        }

        if (data.status === 'error') {
            statusDiv.innerHTML = '<div class="alert alert-danger">Error generating GIFs. Check server logs.</div>';
            pbar.classList.remove('progress-bar-animated', 'progress-bar-striped');
            pbar.classList.add('bg-danger');
            setGiffileButtons(false);
            setGiffileStopButton(false);
        } else if (data.status === 'stopped') {
            statusDiv.innerHTML = '<div class="alert alert-warning">Stopped. You can use Resume to continue this job later.</div>';
            pbar.classList.remove('progress-bar-animated', 'progress-bar-striped');
            progressText.textContent = data.message || progressText.textContent;
            setGiffileButtons(false);
            setGiffileStopButton(false);
        } else if (data.status === 'stopping') {
            statusDiv.innerHTML = '<div class="alert alert-warning">Stopping... finishing current work.</div>';
            setTimeout(function() { giffilePoll(job_id); }, 3000);
        } else if (pct >= 100) {
            statusDiv.innerHTML = '<div class="alert alert-success">Done! GIFs saved to: <code>' + document.getElementById('outputdir').value.trim() + '</code></div>';
            pbar.classList.remove('progress-bar-animated', 'progress-bar-striped');
            progressText.textContent = data.message ? '100% - ' + data.message : '100%';
            setGiffileButtons(false);
            setGiffileStopButton(false);
        } else {
            setTimeout(function() { giffilePoll(job_id); }, 3000);
        }
    }).fail(function() {
        setTimeout(function() { giffilePoll(job_id); }, 5000);
    });
}
