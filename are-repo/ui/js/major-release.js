var serverbase = '../';

var downloadReportLabels = {
    species: 'species',
    cell_type: 'cell_type',
    archive: 'archive',
    brain_region: 'brain_region'
};

var downloadReportTypes = ['species', 'cell_type', 'archive', 'brain_region'];
var latestDownloadReports = {};
var latestDownloadsPerQuarterRows = [];
var downloadReportSort = {};
var selectedHitLogFiles = null;

function formatNumber(value) {
    return Number(value || 0).toLocaleString('en-US');
}

function reportPrefix(reportType) {
    return 'downloads_' + downloadReportLabels[reportType];
}

function setReportStatus(reportType, message) {
    document.getElementById(reportPrefix(reportType) + '_status').innerText = message || '';
}

function setReportTotal(reportType, total) {
    document.getElementById(reportPrefix(reportType) + '_total').innerText = total || 0;
}

function setReportTotalCells(reportType, totalCells) {
    document.getElementById(reportPrefix(reportType) + '_total_cells').innerText = totalCells || 0;
}

function renderDownloadsReport(reportType, rows) {
    var tbody = document.querySelector('#' + reportPrefix(reportType) + '_table tbody');
    tbody.innerHTML = '';

    rows.forEach(function(row) {
        var tr = document.createElement('tr');
        var label = document.createElement('td');
        var cells = document.createElement('td');
        var total = document.createElement('td');

        label.innerText = row.label || '';
        cells.innerText = row.NumberOfCells === null ? '0' : row.NumberOfCells;
        total.innerText = row.Totalnumber === null ? '0' : row.Totalnumber;

        tr.appendChild(label);
        tr.appendChild(cells);
        tr.appendChild(total);
        tbody.appendChild(tr);
    });
}

function sortDownloadsReport(reportType, field) {
    var rows = latestDownloadReports[reportType] || [];
    var current = downloadReportSort[reportType] || {};
    var direction = current.field === field && current.direction === 'asc' ? 'desc' : 'asc';

    rows.sort(function(a, b) {
        var left = a[field];
        var right = b[field];

        if (field === 'label') {
            left = (left || '').toString().toLowerCase();
            right = (right || '').toString().toLowerCase();
            if (left < right) return direction === 'asc' ? -1 : 1;
            if (left > right) return direction === 'asc' ? 1 : -1;
            return 0;
        }

        left = Number(left || 0);
        right = Number(right || 0);
        return direction === 'asc' ? left - right : right - left;
    });

    downloadReportSort[reportType] = {
        field: field,
        direction: direction
    };
    renderDownloadsReport(reportType, rows);
}

function applyCurrentSort(reportType) {
    var current = downloadReportSort[reportType];
    if (!current) {
        return;
    }
    var direction = current.direction;
    current.direction = direction === 'asc' ? 'desc' : 'asc';
    sortDownloadsReport(reportType, current.field);
}

function loadDownloadsReport(reportType) {
    var prefix = reportPrefix(reportType);
    var button = document.getElementById(prefix + '_button');
    var startDate = document.getElementById('downloads_start_date').value;
    var endDate = document.getElementById('downloads_end_date').value;

    if (!startDate || !endDate) {
        setReportStatus(reportType, 'Please select both dates.');
        return Promise.reject(new Error('Please select both dates.'));
    }

    button.disabled = true;
    setReportStatus(reportType, 'Loading...');
    setReportTotal(reportType, 0);
    setReportTotalCells(reportType, 0);
    renderDownloadsReport(reportType, []);

    return fetch(serverbase + 'major_release/downloads_report/' + reportType, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            start_date: startDate,
            end_date: endDate
        })
    })
    .then(function(response) {
        return response.json().then(function(data) {
            if (!response.ok) {
                throw new Error(data.message || 'Request failed');
            }
            return data;
        });
    })
    .then(function(data) {
        var rows = data.data || [];
        latestDownloadReports[reportType] = rows;
        applyCurrentSort(reportType);
        renderDownloadsReport(reportType, rows);
        setReportTotal(reportType, data.total || 0);
        setReportTotalCells(reportType, data.total_cells || 0);
        setReportStatus(reportType, 'Found ' + rows.length + ' rows.');
    })
    .catch(function(error) {
        setReportStatus(reportType, error.message);
    })
    .finally(function() {
        button.disabled = false;
    });
}

function loadAllDownloadsReports() {
    var button = document.getElementById('downloads_run_all_button');
    var startDate = document.getElementById('downloads_start_date').value;
    var endDate = document.getElementById('downloads_end_date').value;

    if (!startDate || !endDate) {
        downloadReportTypes.forEach(function(reportType) {
            setReportStatus(reportType, 'Please select both dates.');
        });
        return;
    }

    button.disabled = true;
    Promise.allSettled(downloadReportTypes.map(function(reportType) {
        return loadDownloadsReport(reportType);
    })).finally(function() {
        button.disabled = false;
    });
}

function setHitLogFolder(input) {
    selectedHitLogFiles = input.files || null;
    var txtCount = 0;
    var folderName = '';
    if (selectedHitLogFiles && selectedHitLogFiles.length) {
        for (var i = 0; i < selectedHitLogFiles.length; i++) {
            if ((selectedHitLogFiles[i].name || '').toLowerCase().endsWith('.txt')) {
                txtCount += 1;
            }
        }
        var firstPath = selectedHitLogFiles[0].webkitRelativePath || selectedHitLogFiles[0].name || '';
        folderName = firstPath.split('/')[0] || '';
    }
    document.getElementById('hit_log_selected_status').innerText = txtCount
        ? folderName + ': ' + txtCount + ' txt file(s) selected.'
        : 'No .txt log files selected.';
}

function analyzeHitLogs() {
    var status = document.getElementById('hit_log_status');
    var button = document.getElementById('hit_log_analysis_button');
    if (!selectedHitLogFiles || !selectedHitLogFiles.length) {
        status.innerHTML = '<span class="text-warning">Choose a folder first.</span>';
        return;
    }

    var formData = new FormData();
    var txtCount = 0;
    for (var i = 0; i < selectedHitLogFiles.length; i++) {
        if ((selectedHitLogFiles[i].name || '').toLowerCase().endsWith('.txt')) {
            formData.append('files', selectedHitLogFiles[i], selectedHitLogFiles[i].webkitRelativePath || selectedHitLogFiles[i].name);
            txtCount += 1;
        }
    }
    if (!txtCount) {
        status.innerHTML = '<span class="text-warning">No .txt log files found in the selected folder.</span>';
        return;
    }

    button.disabled = true;
    status.innerHTML = 'Analyzing ' + txtCount + ' log file(s)...';

    fetch(serverbase + 'major_release/analyze_hit_logs', {
        method: 'POST',
        body: formData
    })
    .then(function(response) {
        return response.json().then(function(data) {
            if (!response.ok) {
                throw new Error(data.message || 'Analysis failed');
            }
            return data;
        });
    })
    .then(function(data) {
        var jspMessage = data.statistics_jsp
            ? '<br><span class="text-muted">statistics.jsp accumulated: added Hits ' +
                formatNumber(data.statistics_jsp.hit_delta_total || 0) +
                ', Hits total ' +
                formatNumber(data.statistics_jsp.hit_total || 0) +
                ', country rows ' + formatNumber(data.statistics_jsp.country_rows_updated || 0) +
                ', country Hits total ' + formatNumber(data.statistics_jsp.country_total_hits || 0) +
                '.</span>'
            : '';
        status.innerHTML =
            'Done. Files: ' + data.files_processed +
            ', counted 200 hits: ' + formatNumber(data.lines_counted) +
            ', unique IPs: ' + formatNumber(data.total_unique_ips) +
            ', total hits: ' + formatNumber(data.total_hits) +
            ', countries resolved: ' + formatNumber(data.countries_resolved || 0) +
            '. <a href="' + data.per_quarter.url + '">perQuarter.xlsx</a>' +
            ' | <a href="' + data.access_country.url + '">AccessCountry.xlsx</a>' +
            jspMessage +
            '<br><span class="text-muted">' + (data.country_note || '') + '</span>';
    })
    .catch(function(error) {
        status.innerHTML = '<span class="text-danger">' + error.message + '</span>';
    })
    .finally(function() {
        button.disabled = false;
    });
}

function revertHitLogStatistics() {
    var status = document.getElementById('hit_log_status');
    var button = document.getElementById('hit_log_revert_button');

    button.disabled = true;
    status.innerHTML = 'Reverting statistics.jsp...';

    fetch(serverbase + 'major_release/revert_statistics', {
        method: 'POST'
    })
    .then(function(response) {
        return response.json().then(function(data) {
            if (!response.ok) {
                throw new Error(data.message || 'Revert failed');
            }
            return data;
        });
    })
    .then(function(data) {
        status.innerHTML = '<span class="text-success">' + (data.message || 'statistics.jsp reverted.') + '</span>';
    })
    .catch(function(error) {
        status.innerHTML = '<span class="text-danger">' + error.message + '</span>';
    })
    .finally(function() {
        button.disabled = false;
    });
}

function setDownloadsQuarterStatus(message) {
    document.getElementById('downloads_quarter_status').innerText = message || '';
}

function renderDownloadsPerQuarterChart(rows, rangeLabel) {
    var categories = rows.map(function(row) {
        return row.label;
    });
    var neuronFiles = rows.map(function(row) {
        return Number(row.NeuronFiles || 0);
    });
    var auxillaryFiles = rows.map(function(row) {
        return Number(row.AuxillaryFiles || 0);
    });

    if (!window.Highcharts) {
        setDownloadsQuarterStatus('Highcharts did not load.');
        return;
    }

    Highcharts.chart('downloads_quarter_chart', {
        chart: {
            type: 'column',
            backgroundColor: '#ffffff'
        },
        title: {
            text: 'Downloads per Quarter'
        },
        subtitle: {
            text: rangeLabel || ''
        },
        xAxis: {
            categories: categories,
            labels: {
                rotation: -45
            }
        },
        yAxis: {
            min: 0,
            title: {
                text: 'Downloads'
            }
        },
        tooltip: {
            shared: true,
            valueDecimals: 0
        },
        plotOptions: {
            column: {
                stacking: 'normal'
            }
        },
        credits: {
            enabled: false
        },
        series: [
            {
                name: 'Auxillary Files',
                color: '#00A86B',
                data: auxillaryFiles
            },
            {
                name: 'Neuron Files',
                color: '#246BFE',
                data: neuronFiles
            }
        ]
    });
}

function loadDownloadsPerQuarterChart() {
    var button = document.getElementById('downloads_quarter_button');
    var startDate = document.getElementById('downloads_start_date').value;
    var endDate = document.getElementById('downloads_end_date').value;

    if (!startDate || !endDate) {
        setDownloadsQuarterStatus('Please select both dates.');
        return Promise.reject(new Error('Please select both dates.'));
    }

    button.disabled = true;
    setDownloadsQuarterStatus('Loading downloads per quarter...');
    latestDownloadsPerQuarterRows = [];
    document.getElementById('downloads_quarter_neuron_total').innerText = '0';
    document.getElementById('downloads_quarter_aux_total').innerText = '0';

    return fetch(serverbase + 'major_release/downloads_per_quarter', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            start_date: startDate,
            end_date: endDate
        })
    })
    .then(function(response) {
        return response.json().then(function(data) {
            if (!response.ok) {
                throw new Error(data.message || 'Request failed');
            }
            return data;
        });
    })
    .then(function(data) {
        var rows = data.data || [];
        latestDownloadsPerQuarterRows = rows;
        renderDownloadsPerQuarterChart(rows, data.start_date + ' to ' + data.end_date);
        document.getElementById('downloads_quarter_neuron_total').innerText = formatNumber(data.total_neuron_files || 0);
        document.getElementById('downloads_quarter_aux_total').innerText = formatNumber(data.total_auxillary_files || 0);
        setDownloadsQuarterStatus('Loaded ' + rows.length + ' quarters from ' + data.start_quarter + ' to ' + data.end_quarter + '.');
    })
    .catch(function(error) {
        setDownloadsQuarterStatus(error.message);
    })
    .finally(function() {
        button.disabled = false;
    });
}

function buildDownloadsPerQuarter() {
    var button = document.getElementById('downloads_quarter_build_button');
    if (!latestDownloadsPerQuarterRows.length) {
        setDownloadsQuarterStatus('Run Downloads per Quarter before building.');
        return;
    }

    button.disabled = true;
    setDownloadsQuarterStatus('Building Downloads per Quarter into statistics.jsp...');

    fetch(serverbase + 'major_release/build_downloads_per_quarter', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            rows: latestDownloadsPerQuarterRows
        })
    })
    .then(function(response) {
        return response.json().then(function(data) {
            if (!response.ok) {
                throw new Error(data.message || 'Build failed');
            }
            return data;
        });
    })
    .then(function(data) {
        setDownloadsQuarterStatus(
            (data.message || 'statistics.jsp updated.') +
            ' Added Neuron Files: ' + formatNumber(data.total_neuron_files || 0) +
            ', Auxillary Files: ' + formatNumber(data.total_auxillary_files || 0) + '.'
        );
    })
    .catch(function(error) {
        setDownloadsQuarterStatus(error.message);
    })
    .finally(function() {
        button.disabled = false;
    });
}

function revertDownloadsPerQuarter() {
    var button = document.getElementById('downloads_quarter_revert_button');
    button.disabled = true;
    setDownloadsQuarterStatus('Reverting statistics.jsp...');

    fetch(serverbase + 'major_release/revert_statistics', {
        method: 'POST'
    })
    .then(function(response) {
        return response.json().then(function(data) {
            if (!response.ok) {
                throw new Error(data.message || 'Revert failed');
            }
            return data;
        });
    })
    .then(function(data) {
        setDownloadsQuarterStatus(data.message || 'statistics.jsp reverted.');
    })
    .catch(function(error) {
        setDownloadsQuarterStatus(error.message);
    })
    .finally(function() {
        button.disabled = false;
    });
}

function setRevertStatus(message) {
    document.getElementById('statistics_revert_status').innerText = message || '';
}

function setBuildProgress(percent, message, active) {
    var wrap = document.getElementById('downloads_build_progress_wrap');
    var bar = document.getElementById('downloads_build_progress');
    var value = Math.max(0, Math.min(100, percent || 0));

    wrap.style.display = 'block';
    bar.style.width = value + '%';
    bar.setAttribute('aria-valuenow', value);
    bar.innerText = value + '%';
    if (active === false) {
        bar.classList.remove('progress-bar-animated');
    } else {
        bar.classList.add('progress-bar-animated');
    }
    if (message) {
        setRevertStatus(message);
    }
}

function revertStatistics() {
    var button = document.getElementById('statistics_revert_button');
    button.disabled = true;
    setBuildProgress(25, 'Reverting statistics.jsp...', true);

    fetch(serverbase + 'major_release/revert_statistics', {
        method: 'POST'
    })
    .then(function(response) {
        return response.json().then(function(data) {
            if (!response.ok) {
                throw new Error(data.message || 'Revert failed');
            }
            return data;
        });
    })
    .then(function(data) {
        setBuildProgress(100, data.message || 'statistics.jsp reverted.', false);
    })
    .catch(function(error) {
        setBuildProgress(100, error.message, false);
    })
    .finally(function() {
        button.disabled = false;
    });
}

function buildDownloadsBy(autoRunTried) {
    var button = document.getElementById('downloads_build_button');
    var reports = {};

    setBuildProgress(5, 'Checking report data...', true);
    downloadReportTypes.forEach(function(reportType) {
        if (latestDownloadReports[reportType] && latestDownloadReports[reportType].length) {
            reports[reportType] = latestDownloadReports[reportType];
        }
    });

    if (!Object.keys(reports).length && !autoRunTried) {
        button.disabled = true;
        setBuildProgress(10, 'No report data found. Running all reports first...', true);
        Promise.allSettled(downloadReportTypes.map(function(reportType) {
            return loadDownloadsReport(reportType);
        })).then(function() {
            buildDownloadsBy(true);
        }).finally(function() {
            button.disabled = false;
        });
        return;
    }

    if (!Object.keys(reports).length) {
        setBuildProgress(0, 'No report data available. Check the report errors above.', false);
        return;
    }

    button.disabled = true;
    setBuildProgress(20, 'Sending report data to server...', true);

    fetch(serverbase + 'major_release/build_downloads_by', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            reports: reports
        })
    })
    .then(function(response) {
        setBuildProgress(70, 'Server is updating statistics.jsp...', true);
        return response.json().then(function(data) {
            if (!response.ok) {
                throw new Error(data.message || 'Build failed');
            }
            return data;
        });
    })
    .then(function(data) {
        setBuildProgress(100, data.message || 'statistics.jsp updated.', false);
    })
    .catch(function(error) {
        setBuildProgress(100, error.message, false);
    })
    .finally(function() {
        button.disabled = false;
    });
}
