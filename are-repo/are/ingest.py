import logging
import os
from . import cfg
import pandas as pd
from . import com
from datetime import date 
import math, redis
from . import io
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import time


logging.basicConfig(level=logging.INFO,filename='app.log', filemode='w', format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s')


def read_text_lines(path):
    try:
        with open(path, encoding='utf-8') as fp:
            return fp.readlines()
    except UnicodeDecodeError:
        logging.warning("Reading %s as ISO-8859-1 because UTF-8 decoding failed", path)
        with open(path, encoding='ISO-8859-1') as fp:
            return fp.readlines()


def read_csv_compatible(path, **kwargs):
    try:
        return pd.read_csv(path, encoding='utf-8', **kwargs)
    except UnicodeDecodeError:
        logging.warning("Reading %s as ISO-8859-1 because UTF-8 decoding failed", path)
        return pd.read_csv(path, encoding='ISO-8859-1', **kwargs)


def representint(s):
    try: 
        int(s)
        return True
    except ValueError:
        return False

def _time_stage(timings, stage, func, *args, **kwargs):
    started = time.perf_counter()
    try:
        return func(*args, **kwargs)
    finally:
        if timings is not None:
            timings[stage] = round(time.perf_counter() - started, 4)


def _timing_summary(timings):
    if not timings:
        return ''
    total = timings.get('total')
    stages = [(stage, elapsed) for stage, elapsed in timings.items() if stage != 'total']
    if not stages:
        return '{:.2f}s'.format(total) if total is not None else ''
    slowest_stage, slowest_elapsed = max(stages, key=lambda item: item[1])
    if total is None:
        return 'slowest {}={:.2f}s'.format(slowest_stage, slowest_elapsed)
    return '{:.2f}s; slowest {}={:.2f}s'.format(total, slowest_stage, slowest_elapsed)


def _format_stage_timings(timings):
    return ', '.join(
        '{}={:.4f}s'.format(stage, elapsed)
        for stage, elapsed in sorted(timings.items(), key=lambda item: item[0])
    )


def ingestexecute(neuron_name,neurontomeas,neurontometa,ndomains,timings=None, session=None, return_rows=False):
    # takes one neuron as parameter
    # reads metadata as provided by csv and folder mapping to a dictionary
    # read measurements
    # calculate pvec
    # runs ingest region
    # rund ingest neuron
    # copy neuron files to the right place
    # neurontodetmeas dicitionary mapping domain to measurements dictionary 
    pg_insert = session.pg_insert if session is not None else com.insert
    neurontomeas =  changenotrep(neurontomeas.keys(),neurontomeas)
    meas_id = _time_stage(timings, 'pg_insert_summary_measurements', pg_insert, 'measurements', neurontomeas)
    summary_measurements = dict(neurontomeas)
    summary_measurements['id'] = meas_id
    shrinkval_id = _time_stage(timings, 'pg_insert_shrinkagevalue', pg_insert, 'shrinkagevalue', getshrinkage(neurontometa))
    regionid = _time_stage(timings, 'pg_ingestregion', com.ingestregion, neurontometa, session=session)
    #logging.info("neurontometa is {}".format(neurontometa))
    celltypeid = _time_stage(timings, 'pg_ingestcelltype', com.ingestcelltype, neurontometa, session=session)
    neurontometa['uploaddate'] = str(date.today())
    neurontometa['has_soma'] = 'Soma' in ndomains.keys()
    if representint(neurontometa['pmid']):
        neurontometa['doi'] = ''
    else:
        neurontometa['doi'] = neurontometa['pmid']
        neurontometa['pmid'] = -1
    neurontometa['sum_mes_id'] = meas_id 
    neurontometa['shrinkval_id'] = shrinkval_id
    neurontometa['neuron_name'] = neuron_name
    neurontometa['region'] = regionid
    neurontometa['celltype'] = celltypeid
    neurontometa = changenotrep([
        'min_weight',
        'max_weight',
        'max_age',
        'min_age',
        'URL_reference',
        'thickness',
        'pmid'
        ],neurontometa)
    neurontometa = mapvals(neurontometa)
    neurontometa = mapshrinkage(neurontometa)
    neuron_id = _time_stage(timings, 'pg_call_ingest_data', com.ingestneuron, neurontometa, session=session)
    if return_rows:
        return neuron_id, summary_measurements
    return neuron_id

def ingestdetailedmeas(neuron_name,neurontodetmeas, session=None, return_rows=False):
    pg_insert = session.pg_insert if session is not None else com.insert
    meas_ids = {}
    meas_rows = {}
    for item in neurontodetmeas:
        thismeas = neurontodetmeas[item][neuron_name]
        changenotrep(thismeas.keys(),thismeas)
        meas_ids[item] = pg_insert('measurements',thismeas)
        meas_rows[item] = dict(thismeas)
        meas_rows[item]['id'] = meas_ids[item]
    if return_rows:
        return meas_ids, meas_rows
    return meas_ids


def _structure_rows_from_ingest(domains, morpho_attr, detmeas_rows):
    rows = []
    for domain, completeness in domains.items():
        if domain == 'Soma':
            continue
        row = dict(detmeas_rows[domain])
        row['domain'] = domain
        row['completeness'] = completeness
        row['morph_attributes'] = morpho_attr
        rows.append(row)
    return rows
    
    
    
def ingestneuron(neuron_name):
    session = com.get_workflow_session()
    try:
        folder_name = com.getneuronfolder(neuron_name)
        #archive_name = io.namefromfolder(folder_name)
        neurontometa = mapneurontometa(folder_name)
        (neurontomeas,neurontodetmeas) = mapneurontomeasurements(folder_name)
        (ndomains,morpho_attr) = neurondomains(neuron_name,neurontometa[neuron_name], folder_name=folder_name)
        neuron_id, summary_measurements = ingestexecute(
            neuron_name,
            neurontomeas[neuron_name],
            neurontometa[neuron_name],
            ndomains,
            session=session,
            return_rows=True,
        )
        detmeas_ids, detmeas_rows = ingestdetailedmeas(
            neuron_name,
            neurontodetmeas,
            session=session,
            return_rows=True,
        )
        domain_map = dict(ndomains)
        com.ingestdomain(neuron_id,domain_map,morpho_attr,detmeas_ids, session=session)
        pvec_row = io.importpvec(neuron_id,neuron_name,folder_name, session=session)
        io.exportneuron(neuron_name, folder_name, {
            'summary_measurements': summary_measurements,
            'structure_rows': _structure_rows_from_ingest(domain_map, morpho_attr, detmeas_rows),
            'pvec': pvec_row,
        })
        result= {
            'status': 'success',
            'message': 'Successful ingestion'
        }
    except Exception as e:
        result= {
            'status': 'error',
            'message': str(e)
        }
        com.setneuronerror(neuron_name,str(e))
        logging.exception("Error during ingestion of neuron: {}".format(neuron_name))
    finally:
        com.close_workflow_sessions()
    return result
    

def mapshrinkage(d):
    if d['shrinkage_reported'] == 'Reported' and d['shrinkage_corrected'] == 'Corrected':
        d['shrinkage_reported'] = 'reported and corrected'
    elif d['shrinkage_reported'] == 'Reported':
        d['shrinkage_reported'] = 'reported and not corrected'
    return d

        

def changenotrep(tochange,d):
    for item in tochange:
        #if d[item] == 'Not reported' or d[item] == 'Not applicable':
        #    d[item] = None
        if isinstance(d[item], float):
            if math.isnan(d[item]):
                d[item] = None
    return d

def mapvals(d):
    if d['gender'] == 'Male':
        d['gender'] = 'M'
    elif d['gender'] == 'Female':
        d['gender'] = 'F'
    elif d['gender'] == 'Male/Female':
        d['gender'] = 'M/F'
    elif d['gender'] == 'Not reported' or d['gender'] == 'not reported':
        d['gender'] = 'NR'
        
    return d

def getshrinkage(d):
    shrinkkeys = ['reported_value', 'reported_xy', 'reported_z', 'corrected_value','corrected_xy','corrected_z']
    shrinkd = {item: d[item] for item in shrinkkeys}
    shrinkd = changenotrep(shrinkkeys,shrinkd)
    return shrinkd


def _sanitize_ingest_threads(threads):
    try:
        threads = int(threads)
    except (TypeError, ValueError):
        return 1
    if threads >= 8:
        return 8
    if threads >= 4:
        return 4
    if threads >= 2:
        return 2
    return 1


def _ingest_archive_neuron(folder_name, neuron, neurontometa, neurontomeas, neurontodetmeas, existing_review_neurons=None):
    neuron_name = neuron['neuron_name']
    timings = {}
    total_started = time.perf_counter()
    session = None
    try:
        session = com.get_workflow_session()
        if existing_review_neurons is None:
            exists = _time_stage(timings, 'mysql_check_existing_neuron', com.myneuronexists, neuron_name)
        else:
            exists = neuron_name in existing_review_neurons
            timings['mysql_check_existing_neuron'] = 0.0
        if exists:
            com.updateneuronstatus_fast(session, neuron_name, 'ingested', 'Neuron already exists in review DB')
            timings['total'] = round(time.perf_counter() - total_started, 4)
            logging.info("Ingest timing %s: %s", neuron_name, _format_stage_timings(timings))
            return neuron_name, {
                'status': 'success',
                'message': 'Neuron already exists in review DB',
                'skipped': True,
                'timings': timings,
            }

        thismeta = neurontometa[neuron_name].copy()
        (ndomains,morpho_attr) = _time_stage(timings, 'read_swc_domains', neurondomains, neuron_name, thismeta, folder_name=folder_name)

        neuron_id, summary_measurements = _time_stage(
            timings,
            'ingestexecute_total',
            ingestexecute,
            neuron_name,
            neurontomeas[neuron_name],
            thismeta,
            ndomains,
            timings,
            session=session,
            return_rows=True,
        )
        detmeas_ids, detmeas_rows = _time_stage(
            timings,
            'pg_insert_detailed_measurements',
            ingestdetailedmeas,
            neuron_name,
            neurontodetmeas,
            session=session,
            return_rows=True,
        )
        
        domain_map = dict(ndomains)
        _time_stage(timings, 'pg_insert_domains', com.ingestdomain, neuron_id, domain_map, morpho_attr, detmeas_ids, session=session)
        pvec_row = _time_stage(timings, 'pg_import_pvec', io.importpvec, neuron_id, neuron_name, folder_name, session=session)
        ingest_export_data = {
            'summary_measurements': summary_measurements,
            'structure_rows': _structure_rows_from_ingest(domain_map, morpho_attr, detmeas_rows),
            'pvec': pvec_row,
        }
        _time_stage(timings, 'export_review_mysql_tomcat', io.exportneuron, neuron_name, folder_name, ingest_export_data)
        timings['total'] = round(time.perf_counter() - total_started, 4)
        logging.info("Ingest timing %s: %s", neuron_name, _format_stage_timings(timings))
        return neuron_name, {
            'status': 'success',
            'message': 'Successful ingestion',
            'timings': timings,
        }
    except Exception as e:
        timings['total'] = round(time.perf_counter() - total_started, 4)
        com.setneuronerror(neuron_name,str(e))
        logging.info("Ingest timing %s before error: %s", neuron_name, _format_stage_timings(timings))
        logging.exception("Error during ingestion of neuron: {}".format(neuron_name))
        return neuron_name, {
            'status': 'error',
            'message': str(e),
            'timings': timings,
        }


def _neuron_progress_message(counter, total, neuron_name, neuron_result):
    timing = _timing_summary(neuron_result.get('timings'))
    timing_suffix = ' ({})'.format(timing) if timing else ''
    if neuron_result.get('status') == 'error':
        return 'Error {} / {}: {}{}'.format(counter, total, neuron_name, timing_suffix)
    if neuron_result.get('skipped'):
        return 'Skipped existing neuron {} / {}: {}{}'.format(counter, total, neuron_name, timing_suffix)
    return 'Processed {} / {}: {}{}'.format(counter, total, neuron_name, timing_suffix)


def ingestarchive(folder_name, progress_cb=None, should_stop=None, threads=1):
    # select all neurons with status ready from an archive and ingest them
    threads = _sanitize_ingest_threads(threads)
    com.close_workflow_sessions()
    com.clear_workflow_caches()
    io.clear_transfer_dir_cache()
    r = redis.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', '6379')),
        db=int(os.getenv('REDIS_DB', '0')),
    )
        #archive_name = io.namefromfolder(folder_name)
    neurontometa = mapneurontometa(folder_name)

    (neurontomeas,neurontodetmeas) = mapneurontomeasurements(folder_name)
    # logging.info("neurontodetmeas is {}".format(neurontodetmeas))
    archive_name = io.namefromfolder(folder_name)
    readyneurons = com.getfolderneuronstatus(archive_name) # TODO check if correct
    counter =  0
    targetneurons = [item for item in readyneurons if item['status'] in ('warning','read','error')]
    targetneurons.sort(key=lambda item: item['neuron_name'])
    nneurons = len(targetneurons)
    existing_review_neurons = com.get_existing_mysql_neuron_names(item['neuron_name'] for item in targetneurons)
    result = {}
    if progress_cb:
        progress_cb(
            0,
            nneurons,
            'Loaded {} neuron(s) to ingest with {} thread(s); preloaded {} existing review neuron(s)'.format(
                nneurons,
                threads,
                len(existing_review_neurons),
            ),
        )

    if threads <= 1:
        for neuron in targetneurons:
            if should_stop and should_stop():
                if progress_cb:
                    progress_cb(counter, nneurons, 'Stop requested. Ingest paused after current neuron.', 'stopped')
                break
            neuron_name = neuron['neuron_name']
            if progress_cb:
                progress_cb(counter, nneurons, 'Ingesting {}'.format(neuron_name))
            neuron_name, neuron_result = _ingest_archive_neuron(
                folder_name,
                neuron,
                neurontometa,
                neurontomeas,
                neurontodetmeas,
                existing_review_neurons,
            )
            counter += 1
            if nneurons:
                r.set(folder_name,counter/nneurons)
            if progress_cb:
                progress_cb(counter, nneurons, _neuron_progress_message(counter, nneurons, neuron_name, neuron_result))
            stored_result = dict(neuron_result)
            stored_result.pop('timings', None)
            result[neuron_name] = stored_result
        return result

    iterator = iter(targetneurons)
    pending = {}
    max_pending = max(threads * 2, threads)

    def submit_next(executor):
        if should_stop and should_stop():
            return False
        try:
            neuron = next(iterator)
        except StopIteration:
            return False
        future = executor.submit(
            _ingest_archive_neuron,
            folder_name,
            neuron,
            neurontometa,
            neurontomeas,
            neurontodetmeas,
            existing_review_neurons,
        )
        pending[future] = neuron['neuron_name']
        if progress_cb:
            progress_cb(counter, nneurons, 'Queued {}'.format(neuron['neuron_name']))
        return True

    with ThreadPoolExecutor(max_workers=threads) as executor:
        while len(pending) < max_pending and submit_next(executor):
            pass
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                queued_name = pending.pop(future)
                try:
                    neuron_name, neuron_result = future.result()
                except Exception as e:
                    neuron_name = queued_name
                    neuron_result = {
                        'status': 'error',
                        'message': str(e)
                    }
                    com.setneuronerror(neuron_name,str(e))
                    logging.exception("Error during threaded ingestion of neuron: {}".format(neuron_name))
                counter += 1
                if nneurons:
                    r.set(folder_name,counter/nneurons)
                if progress_cb:
                    progress_cb(counter, nneurons, _neuron_progress_message(counter, nneurons, neuron_name, neuron_result))
                stored_result = dict(neuron_result)
                stored_result.pop('timings', None)
                result[neuron_name] = stored_result
            while len(pending) < max_pending and submit_next(executor):
                pass

    if should_stop and should_stop() and counter < nneurons and progress_cb:
        progress_cb(counter, nneurons, 'Stop requested. Ingest paused after current neuron batch.', 'stopped')
     
    return result
    


def readmeasurements(foldername):
    measurementPath = os.path.join(cfg.datapath, foldername, "Measurements")
    mdfs = {}
    for filename in os.listdir(measurementPath):
        if filename[0] == '.':
            continue
        if filename.find('csv') != -1:
            csvFilePath = os.path.join(measurementPath, filename)
            measurementsDataFrame = read_csv_compatible(csvFilePath, header=0)
            if filename[-7] == '-':
                label = filename[-6:-4]
            else:
                label = filename[-7:-4]
            mdfs[label]= measurementsDataFrame
    return mdfs

def readmetadata(archivename):
    # read metadata from file, assign dict values to dict of metadata labels
    # if only one group, assign dict values to dict with label 'default'
    filepath = os.path.join(cfg.metapath,archivename,archivename + '.csv')
    anmdf = read_csv_compatible(filepath, header=0)
    (rows,cols) = anmdf.shape
    metadict = {}
    if cols > 2:
        for col in anmdf.columns[1:]:
            #grouplabel = anmdf.iat[0,icol]
            metadict[col] = {}
        for ix in range(rows):
            itemlabel = anmdf.iat[ix,0]
            for jx in range(1,cols):
                grouplabel = anmdf.columns[jx]
                metadict[grouplabel][itemlabel] = anmdf.iat[ix,jx]
    else:
        metadict = {'default': {}}
        for ix in range(rows):
            itemlabel = anmdf.iat[ix,0]
            metadict['default'][itemlabel] = anmdf.iat[ix,1]
    return metadict

def mapneurontometa(archivename):
    # generates neuron to metadata map
    # check number of metadata groups
    # if more than one, generate neuron to group map 
    # and generate group to metadata map 
    # if only one, map the neurons directly to the metadata
    # returns the neuron to metadata map
    neurontometa = {}
    grouptometa = readmetadata(archivename)
    base_path = os.path.join(cfg.metapath,archivename)

    # CAP issue for CNG Version folder
    if os.path.exists(os.path.join(base_path, 'CNG Version')):
        thismetapath = os.path.join(base_path, 'CNG Version')
    elif os.path.exists(os.path.join(base_path, 'CNG version')):
        thismetapath = os.path.join(base_path, 'CNG version')
    else:
        raise FileNotFoundError('CNG Version / CNG version not found')

    if len(grouptometa) == 1:
        
        neurons=os.listdir(thismetapath)
        for item in neurons:
            neurontometa[item[0:-8]] = grouptometa['default']
    else:
    
        metadatadirs = os.listdir(thismetapath)
        for item in metadatadirs:
            thispath = os.path.join(thismetapath,item)
            if not os.path.isdir(thispath):
                continue
            neurons = os.listdir(thispath)
            for neuron in neurons:
                try: 
                    neurontometa[neuron[0:-8]] = grouptometa[item]
                except KeyError as e:
                    raise KeyError(str(e) + ' Meta data group not found')
    return neurontometa

def mapneurontomeasurements(foldername):
    # generates measurements to neurons map
    # read different type of measurements for the archive 
    # map all neurons to measurements
    mdfs = readmeasurements(foldername)
    summeas = mdfs['All']
    neuronstomeas = {}
    (nrows,ncols) = summeas.shape
    for irow in range(nrows):
        neuron_name = str(summeas.iat[irow,0])
        neuronstomeas[neuron_name] = {}
        neuronstomeas[neuron_name][summeas.columns[1]] = summeas.iat[irow,1]
        for icol in range(2,ncols):
            neuronstomeas[neuron_name][summeas.columns[icol]] = summeas.iat[irow,icol]
    dets = ['AP','APA','APB','AX','BS','BSA','NEU','PR']
    neuronstodetmeas = {}
    for item in dets:
        thismes = mdfs[item]
        thisdet = {}
        (nrows,ncols) = thismes.shape
        for irow in range(nrows):
            neuron_name = str(thismes.iat[irow,0])
            thisdet[neuron_name] = {}
            thisdet[neuron_name][thismes.columns[1]] = thismes.iat[irow,1]
            for icol in range(2,ncols):
                thisdet[neuron_name][thismes.columns[icol]] = thismes.iat[irow,icol]
        neuronstodetmeas[item] = thisdet
    return (neuronstomeas,neuronstodetmeas)

def mapneurontodetailedmeasurements(archive_name):
    # generates measurements to neurons map
    # read different type of measurements for the archive 
    # map all neurons to measurements
    #TODO to adapt to detailed
    mdfs = readmeasurements(archive_name)

    detailedtypes = ['AP','APA','APB','AX','BS','BSA','NEU','PR']

    
    neuronstomeas = {}
    for item in detailedtypes:
        detmeas = mdfs[item]
        (nrows,ncols) = detmeas.shape
        for irow in range(nrows):
            neuron_name = detmeas.iat[irow,0]
            #if neuron_name in neuronstomeas.keys()
            neuronstomeas[neuron_name] = {}
            for icol in range(1,ncols):
                neuronstomeas[item][neuron_name][detmeas.columns[icol]] = detmeas.iat[irow,icol]

    return neuronstomeas

def neurondomains(neuron_name,neuronmeta, folder_name=None):
    integrity = neuronmeta['Physical integrity']
    
    #reads swc file and finds neuron domains and if it has soma or not
    if folder_name is None:
        folder_name = com.getneuronfolder(neuron_name)
    filename = os.path.join(cfg.datapath, folder_name,'CNG Version',neuron_name + '.CNG.swc')
    minrad = 10000
    maxrad = -10000
    noDim = True
    hasDim = False
    firstRead = True
    lines = read_text_lines(filename)
    domaincount = [0] * 8
    for line in lines:
        if line[0] == '#' or len(line) < 3:
            continue
        else:
            elems = line.strip().split()
            if firstRead and int(elems[1]) != 1:
                prevradius = float(elems[5]) 
                firstRead = False
            domaincount[int(elems[1])] += 1
            if maxrad < float(elems[4]):
                maxrad = float(elems[4])
            if minrad > float(elems[4]):
                minrad = float(elems[4])

            hasDim = hasDim or (int(elems[1]) != 1 and float(elems[5]) > 1)
            if int(elems[1]) != 1:
                noDim = noDim and float(elems[5]) == prevradius
                # logging.info("noDim is {}".format(noDim))
                # logging.info("before noDim is {}".format(noDim))
                # logging.info("elem5 is {}".format(elems[5]))
                # logging.info("prevradius is {}".format(prevradius))
                prevradius = float(elems[5])
        # logging.info("elems is {}".format(elems[1]))
    #3D -  has a variation in diameter
    is3D = maxrad - minrad > 3

    # Check diameter override from csv
    diaoverride = neuronmeta['diameter']  
    if isinstance(diaoverride,float): # is NaN
        # if it is null
        # hasDim = not noDim
        # hasDim = False
        pass

    elif diaoverride in ('TRUE','True'): # Overridden to True
        hasDim = True

    elif diaoverride in ('FALSE','False'): # Overridden to False
        hasDim = False

    else:
        hasDim = not noDim

    # Code for deciding morphological a2tributes.
    # Angles hardcoded, as it was in previous ingestion. 
    if hasDim and is3D:
        # Diameter, 3D, Angles
        morpho_attr = 3
    elif hasDim and not is3D:
        # Diameter, 2D, Angles
        morpho_attr = 1
    elif not hasDim and is3D:
        # No Diameter, 3D, Angles
        morpho_attr = 7
    else:
        # No Diameter, 2D, Angles
        morpho_attr = 5
    # logging.info("Diameter is morpho_attr is {}".format(morpho_attr))

    #establish dictionary of domains detected
    domains = {'Soma': domaincount[1] > 0,
        "AP": domaincount[4] > 0,
        "BS": domaincount[3] > 0,
        "AX": domaincount[2] > 0,
        "NEU": domaincount[6] > 0,
        "PR": domaincount[7] > 0
    }
    domcheck = [key for key in domains if domains[key]]
    domres = {}
    # parse integrity
    if  isinstance(integrity,float):
        # is nan value
        integdict = {item: ('Incomplete' if item == 'AX' else 'Moderate') for item in domcheck}
    else:
        integrity = integrity.replace('& ','')
        # make integerity string  array 
        integarr = integrity.split()
        integdict = {item: ('Incomplete' if item == 'AX' else 'Moderate') for item in domcheck }
        try:
            if len(integarr) > 2:
                for item in domcheck:
                    if len(integarr) == 3:
                        integdict[item] = integarr[2]
                    else:
                        integdict[item] = integarr[1]
                if domaincount[2] > 0:
                    if len(integarr) == 3:
                        integdict['AX'] = integarr[2]
                    else:
                        integdict['AX'] = integarr[3]
            elif len(integarr) > 0:
                for item in domcheck:
                    integdict[item] = integarr[1]
                if domaincount[2] > 0 and 'Axon' not in integarr:
                    integdict['AX'] = 'Incomplete'
        except KeyError as e:
            raise KeyError('Physical integrity element not in domains{}'.format(str(e)))
    return (integdict,morpho_attr)
                
