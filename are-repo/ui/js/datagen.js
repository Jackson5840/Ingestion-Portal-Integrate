var serverbase = '../';

function toWslPath(p) {
    p = (p || '').trim();
    var m = p.match(/^\\\\wsl\.localhost\\[^\\]+\\(.*)/);
    if (m) {
        return '/' + m[1].replace(/\\/g, '/');
    }
    m = p.match(/^([A-Za-z]):[\\\/](.*)/);
    if (m) {
        return '/mnt/' + m[1].toLowerCase() + '/' + m[2].replace(/\\/g, '/');
    }
    return p;
}

function datagenElements(kind) {
    return {
        fileInput: document.getElementById(kind + '_xlsx'),
        outputInput: document.getElementById(kind + '_outputdir'),
        database: document.getElementById(kind + '_database'),
        button: document.getElementById(kind + '_btn'),
        status: document.getElementById(kind + '_status'),
        progressWrap: document.getElementById(kind + '_progress_wrap'),
        pbar: document.getElementById(kind + '_pbar'),
        progressText: document.getElementById(kind + '_progress_text'),
        log: document.getElementById(kind + '_log')
    };
}

function startDataGEN(kind) {
    var el = datagenElements(kind);
    var file = el.fileInput.files && el.fileInput.files.length ? el.fileInput.files[0] : null;
    var outputdir = toWslPath(el.outputInput.value);
    var database = el.database ? el.database.value : 'main';
    el.outputInput.value = outputdir;

    if (!file) {
        el.status.innerHTML = '<div class="alert alert-warning">Choose an xlsx file first.</div>';
        return;
    }
    if (!outputdir) {
        el.status.innerHTML = '<div class="alert alert-warning">Output folder is required.</div>';
        return;
    }

    var formData = new FormData();
    formData.append('xlsx', file, file.name);
    formData.append('outputdir', outputdir);
    formData.append('database', database);

    el.button.disabled = true;
    el.status.innerHTML = '<div class="alert alert-info">Starting...</div>';
    el.progressWrap.style.display = 'flex';
    el.pbar.style.width = '0%';
    el.pbar.textContent = '0%';
    el.pbar.classList.remove('bg-danger', 'bg-warning');
    el.pbar.classList.add('progress-bar-animated', 'progress-bar-striped', 'bg-success');
    el.progressText.textContent = '';
    el.log.style.display = 'none';
    el.log.textContent = '';

    $.ajax({
        url: serverbase + 'datagen/generate/' + encodeURIComponent(kind),
        type: 'POST',
        data: formData,
        processData: false,
        contentType: false,
        success: function(data) {
            if (data.status === 'error') {
                el.status.innerHTML = '<div class="alert alert-danger">Error: ' + (data.message || 'Request failed') + '</div>';
                el.button.disabled = false;
                return;
            }
            el.status.innerHTML = '<div class="alert alert-info">Running job: <strong>' + data.job_id + '</strong> (' + (data.database || database) + ')</div>';
            setTimeout(function() { pollDataGEN(kind, data.job_id); }, 800);
        },
        error: function(xhr) {
            var message = xhr.responseJSON && xhr.responseJSON.message ? xhr.responseJSON.message : 'Request failed. Check server logs.';
            el.status.innerHTML = '<div class="alert alert-danger">Error: ' + message + '</div>';
            el.button.disabled = false;
        }
    });
}

function pollDataGEN(kind, jobId) {
    var el = datagenElements(kind);
    $.get(serverbase + 'datagen/status/' + encodeURIComponent(jobId), function(data) {
        var pct = Math.round(data.progress || 0);
        el.pbar.style.width = pct + '%';
        el.pbar.textContent = pct + '%';
        el.pbar.setAttribute('aria-valuenow', pct);

        if (data.total > 0) {
            el.progressText.textContent = (data.message || 'Generating') + ' - ' + data.current + ' / ' + data.total;
        } else {
            el.progressText.textContent = data.message || '';
        }

        if (data.log && data.log.length) {
            el.log.style.display = 'block';
            el.log.textContent = data.log.join('\n');
            el.log.scrollTop = el.log.scrollHeight;
        }

        if (data.status === 'success' || data.status === 'warning') {
            el.pbar.classList.remove('progress-bar-animated', 'progress-bar-striped');
            if (data.status === 'warning') {
                el.pbar.classList.remove('bg-success');
                el.pbar.classList.add('bg-warning');
            }
            var result = data.result || {};
            var alertClass = data.status === 'success' ? 'alert-success' : 'alert-warning';
            el.status.innerHTML = '<div class="alert ' + alertClass + '">Done. Generated ' +
                (result.generated || 0) + ' / ' + (result.total || data.total || 0) +
                ', missing ' + (result.missing || 0) +
                ', failed ' + (result.failed || 0) +
                '. Output: <code>' + (data.outputdir || el.outputInput.value) + '</code>' +
                (data.database ? ' Database: <code>' + data.database + '</code>' : '') +
                '</div>';
            el.button.disabled = false;
        } else if (data.status === 'error') {
            el.pbar.classList.remove('progress-bar-animated', 'progress-bar-striped', 'bg-success');
            el.pbar.classList.add('bg-danger');
            el.status.innerHTML = '<div class="alert alert-danger">Error: ' + (data.message || 'DataGEN failed') + '</div>';
            el.button.disabled = false;
        } else {
            setTimeout(function() { pollDataGEN(kind, jobId); }, 1200);
        }
    }).fail(function() {
        setTimeout(function() { pollDataGEN(kind, jobId); }, 3000);
    });
}
