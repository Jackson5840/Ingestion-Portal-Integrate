import psycopg2
import psycopg2.extras
import mysql.connector as mysc
from . import cfg
from . import io
from datetime import datetime
import json,validators
import logging
import threading
import time

_checkexists_cache = {}
_pg_region_cache = {}
_pg_celltype_cache = {}
_publication_cache = {}
_checkexists_lock = threading.RLock()
_pg_reference_lock = threading.RLock()
_publication_lock = threading.RLock()
_TRANSIENT_MYSQL_ERRORS = {1205, 1213}


def clear_checkexists_cache():
    with _checkexists_lock:
        _checkexists_cache.clear()


def clear_reference_caches():
    with _pg_reference_lock:
        _pg_region_cache.clear()
        _pg_celltype_cache.clear()
    with _publication_lock:
        _publication_cache.clear()


def clear_workflow_caches():
    clear_checkexists_cache()
    clear_reference_caches()


def _is_duplicate_error(exc):
    return getattr(exc, 'errno', None) == 1062


def _is_transient_mysql_error(exc):
    return getattr(exc, 'errno', None) in _TRANSIENT_MYSQL_ERRORS


def _execute_mysql_with_retry(cur, statement, attempts=3):
    for attempt in range(attempts):
        try:
            cur.execute(statement)
            return
        except mysc.Error as exc:
            if not _is_transient_mysql_error(exc) or attempt == attempts - 1:
                raise
            time.sleep(0.2 * (attempt + 1))


def checkexists_cached(table, indexfield, fields):
    normalized = {}
    for key, value in fields.items():
        if value is None:
            normalized[key] = 'Not reported'
        elif isinstance(value, (float, int)):
            normalized[key] = str(value)
        else:
            normalized[key] = str(value)
    cache_key = (
        cfg.dbsel,
        table,
        indexfield,
        tuple(sorted(normalized.items())),
    )
    with _checkexists_lock:
        if cache_key not in _checkexists_cache:
            _checkexists_cache[cache_key] = checkexists(table, indexfield, dict(normalized))
        return _checkexists_cache[cache_key]


def pgconnect(f):
    #decorator for postgres operations
    def pgconnect_(*args, **kwargs):
        conn = psycopg2.connect(
            host=cfg.pg_host,
            port=cfg.pg_port,
            database=cfg.pg_database,
            user=cfg.pg_user,
            password=cfg.pg_password,
        )
        conn.autocommit = True
        try:
            rv = f(conn, *args, **kwargs)
        except Exception:
            raise
        finally:
            conn.close()
        return rv
    return pgconnect_


def escapechars(a_string):
    tdict = {
        "]":  "",
        "[":  "",
        "^":  "",
        "$":  "",
        "'": "''"
    }
    for item in tdict:
        a_string = a_string.replace(item, tdict[item])
    return a_string



def myconnect(f):
    #decorator for MySQL operations
    def myconnect_(*args, **kwargs):
        conn = mysc.connect(
            user=cfg.dbuser,
            password=cfg.dbpass,
            host=cfg.dbhost,
            database=cfg.dbsel,
            auth_plugin=cfg.db_auth_plugin,
        )
        conn.autocommit = True
        try:
            rv = f(conn, *args, **kwargs)
        except Exception:
            raise
        finally:
            conn.close()
        return rv
    return myconnect_


def myinsert_with_cursor(cur, tablename, data):
    data = {item: data[item] for item in data if data[item] is not None}
    fields = ",".join(data.keys())
    values = "','".join([str(item).replace("'","''") for item in data.values()])
    statement = """INSERT INTO {}({}) VALUES ('{}') """.format(tablename,fields,values)
    _execute_mysql_with_retry(cur, statement)
    cur.execute("select LAST_INSERT_ID()")
    result = cur.fetchone()
    return result[0]


def deletefromjson(akey,aval,jsonfile):
    with open(jsonfile, 'r') as data_file:
        d = json.load(data_file)

    olddata = d['data']
    newdata = [item for item in olddata if item[akey] != aval]

    with open(jsonfile, 'w') as data_file:
        json.dump({'data': newdata}, data_file)
    

@myconnect
def updateuploaddate(conn,neuron_list,dt_string,olddate):
    if not neuron_list:
        return
    cur = conn.cursor()
    neuron_names = "','".join(neuron_list)
    stmt = """UPDATE deposition 
    INNER JOIN neuron ON neuron.neuron_id = deposition.neuron_id 
    SET upload_date = '{}'
    WHERE neuron.neuron_name IN ('{}') AND deposition.upload_date = '{}'
    """.format(dt_string,neuron_names,olddate)
    print(stmt)
    cur.execute(stmt)


@myconnect
def updateuploaddate_archive(conn,archive,dt_string,olddate):
    cur = conn.cursor()
    stmt = """UPDATE deposition 
    INNER JOIN neuron ON neuron.neuron_id = deposition.neuron_id
    INNER JOIN archive ON archive.archive_id = neuron.archive_id
    SET upload_date = '{}'
    WHERE archive.archive_name = '{}' AND deposition.upload_date = '{}'
    """.format(dt_string,archive.replace("'","''"),olddate)
    print(stmt)
    cur.execute(stmt)


@pgconnect
def getarchiveneuronstatus(conn,archive):
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    stmt = "SELECT * FROM ingestion WHERE archive = '{}'".format(archive)
    cur.execute(stmt)
    result = []
    res = cur.fetchone()
    if res:
        res = dict(res)
    while res:
        result.append(res)
        res = cur.fetchone()
        if res:
            res = dict(res)
    return result

@pgconnect
def getfolderneuronstatus(conn,foldername):
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    stmt = """SELECT neuron_id, ingestion_date, message, neuron_name, archive, status, version_id 
    FROM ingestion
    WHERE archive = '{}' 
    AND status IN ('read','ingested','error','warning','public')""".format(foldername)

    cur.execute(stmt)
    result = []
    res = cur.fetchone()
    if res:
        res = dict(res)
    while res:
        result.append(res)
        res = cur.fetchone()
        if res:
            res = dict(res)
    return result    

@pgconnect
def getcurrentversion(conn,table):
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    stmt = "SELECT * FROM {} WHERE active = true".format(table)
    cur.execute(stmt)
    return cur.fetchone()

@pgconnect
def getcurrentversions(conn,table):
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    stmt = "SELECT * FROM {} ORDER BY id DESC offset 1 LIMIT 1".format(table)
    cur.execute(stmt)
    return cur.fetchone()

@pgconnect
def getfirstneuronname(conn,archive):
    #TODO change to mysql and first date 
    cur = conn.cursor()
    stmt = "SELECT neurontotweet FROM ingested_archives WHERE name = '{}' ORDER BY neurontotweet".format(archive)
    cur.execute(stmt)
    res = cur.fetchone()
    if res is None or res[0] is None:
        stmt = "SELECT neuron.name FROM neuron,archive WHERE archive.id = neuron.archive_id and archive.name = '{}' LIMIT 1".format(archive)
        cur.execute(stmt)
        res = cur.fetchone()
    return res[0]

@pgconnect
def setversionarchives(conn,archive,ingestdate,versionid,table):

    cur = conn.cursor()
    stmt = "UPDATE ingested_archives SET {}_id = {} WHERE name = '{}' AND date = '{}'".format(table,versionid,archive,ingestdate)
    cur.execute(stmt)
    cur = conn.cursor()
    stmt = "SELECT major,minor,patch FROM {} WHERE id = {}".format(table,versionid)
    cur.execute(stmt)
    res = cur.fetchone()
    res = list(res)
    res[2] += 1
    cur = conn.cursor()
    stmt = "UPDATE {} SET active = false where id ={}".format(table,versionid)
    cur.execute(stmt)
    stmt = """INSERT INTO {} (major, minor, patch) 
    VALUES ({},{},{})""".format(table, res[0],res[1],res[2])
    cur.execute(stmt)


@pgconnect
def deletearchive(conn,foldername,neuronarr):
    #TODO only recently ingested archive should be deleted, many with same name will be deleted from project db
    archive_name = io.namefromfolder(foldername)
    cur = conn.cursor()
    stmt = "DELETE FROM export WHERE neuron_id IN (SELECT id FROM neuron WHERE archive_id IN (SELECT id FROM archive WHERE name = '{}'))".format(archive_name)
    cur.execute(stmt)
    stmt = "DELETE FROM archive WHERE name = '{}'".format(archive_name)
    cur.execute(stmt)
    if neuronarr:
        stmt = "DELETE FROM ingestion WHERE ingestion.neuron_name IN ('{}')".format("','".join(neuronarr))
        cur.execute(stmt)
    stmt = "DELETE FROM ingested_archives WHERE foldername = '{}'".format(foldername)
    cur.execute(stmt)

@pgconnect
def deletearchiveingestion(conn,foldername):
    archive_name = io.namefromfolder(foldername)
    cur = conn.cursor()
    stmt = "DELETE FROM archive WHERE name = '{}'".format(archive_name)
    cur.execute(stmt)
    stmt = "UPDATE ingestion SET status='read' WHERE archive = '{}'".format(archive_name)
    cur.execute(stmt)

@pgconnect
def deleteingestedarchive(conn,foldername):
    cur = conn.cursor()
    stmt = "DELETE FROM ingested_archives WHERE foldername = '{}'".format(foldername)
    cur.execute(stmt)



@myconnect
def countneurons(conn):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM neuron")
    res = cur.fetchone()
    return res[0]

@myconnect
def getmetrics(conn):
    metrics = {}
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM neuron")
    res = cur.fetchone()
    metrics["nneurons"] = res[0]
    cur.execute("select count(1) from archive")
    res = cur.fetchone()
    metrics["nlabs"] = res[0]
    cur.execute("""select count(distinct brainRegion.name) 
        from brainRegion, brainRegion_neuron 
        where brainRegion_neuron.brainRegionLevel =2 and brainRegion_neuron.brainRegionId= brainRegion.id""")
    res = cur.fetchone()
    metrics["nregions"] = res[0]
    cur.execute("""select count(distinct cellType.name) 
        from cellType, cellType_neuron 
        where cellType_neuron.cellTypeLevel =3 and cellType_neuron.cellTypeId= cellType.id""")
    res = cur.fetchone()
    metrics["ncelltypes"] = res[0]
    cur.execute("select count(1) from species")
    res = cur.fetchone()
    metrics["nspecies"] = res[0]
    
    return metrics


@myconnect
def deleteingestedneurons(conn,neuronarr):
    cur = conn.cursor()
    stmt = "DELETE FROM neuron WHERE neuron.neuron_name IN ('{}')".format("','".join(neuronarr))
    cur.execute(stmt)


@pgconnect
def deletemeasurements(conn,measids):
    if len(measids) > 0:
        cur = conn.cursor()
        measids = [str(item) for item in measids]
        stmt = "DELETE FROM measurements WHERE measurements.id IN ({})".format(",".join(measids))
        cur.execute(stmt)

@pgconnect
def getarchiveingestionstatus(conn,foldername):
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    stmt = "SELECT name, date, message, status, json,foldername from ingested_archives where foldername = '{}'".format(foldername)
    cur.execute(stmt)
    res = cur.fetchone()
    if res:
        result = dict(res)
    else:
        result = {}
    return result


@pgconnect
def getarchiveversionrefs(conn, foldername):
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    stmt = """
    SELECT id, name, foldername, date, version_id, pubversion_id
    FROM ingested_archives
    WHERE foldername = '{}'
    ORDER BY date DESC, id DESC
    LIMIT 1
    """.format(foldername)
    cur.execute(stmt)
    res = cur.fetchone()
    return dict(res) if res else {}


@pgconnect
def rollbackversiontable(conn, table, previous_id):
    if previous_id is None:
        return {"status": "skipped", "message": "{} reference missing".format(table)}

    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT id, major, minor, patch, active FROM {} WHERE id = {}".format(table, previous_id))
    previous = cur.fetchone()
    if previous is None:
        return {"status": "error", "message": "{} previous version {} not found".format(table, previous_id)}

    cur.execute("SELECT id, major, minor, patch, active FROM {} WHERE active = true ORDER BY id DESC LIMIT 1".format(table))
    current = cur.fetchone()
    if current is None:
        return {"status": "error", "message": "{} current active version not found".format(table)}

    previous = dict(previous)
    current = dict(current)

    if current["id"] == previous["id"]:
        return {"status": "skipped", "message": "{} already active at {}".format(table, previous["id"])}

    same_series = current["major"] == previous["major"] and current["minor"] == previous["minor"]
    next_patch = current["patch"] == previous["patch"] + 1
    if not (same_series and next_patch and current["id"] > previous["id"]):
        return {
            "status": "error",
            "message": "{} active version {} does not look like the next version after {}".format(table, current["id"], previous["id"]),
        }

    cur = conn.cursor()
    cur.execute("UPDATE {} SET active = false WHERE id = {}".format(table, current["id"]))
    cur.execute("UPDATE {} SET active = true WHERE id = {}".format(table, previous["id"]))
    cur.execute("DELETE FROM {} WHERE id = {}".format(table, current["id"]))

    return {"status": "success", "message": "{} rolled back from {} to {}".format(table, current["id"], previous["id"])}

@pgconnect
def getpvec(conn,neuron_id):
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute('select * from pvec where neuron_id ={}'.format(neuron_id))
    res = cur.fetchall()
    if res:
        result = dict(res[0])
    else:
        result = {}
    return result   


def exportpvec(neuron_id,oldid):
    dpvec = getpvec(neuron_id)
    dpvec["Sfactor"] = dpvec.pop("sfactor")
    del dpvec["id"]
    dpvec["neuron_id"] = oldid
    coeffs = dpvec["coeffs"]
    del dpvec["coeffs"]
    dcoeffs = {"coeff{0:0=2d}".format(i): j for (i,j) in enumerate(coeffs)}
    newd = {**dpvec,**dcoeffs}
    myinsert("persistance_vector",newd)


@myconnect
def insertbrainregions(conn,reglist,neuron_id):
    # inserts a region by checking if exists in region table and then in the connecting table 
    #TODO should loop over pairs tuplets with (label,regions)
    #egionlabels = ['region1','region2','region3','region3B']
    cur = conn.cursor(buffered=True)
    level = 0
    for item in reglist:
        level += 1
        name = escapechars(item[1])
        statement = "select id from brainRegion where name = '{}'".format(name)
        cur.execute(statement)
        res = cur.fetchone()  
        if res is None:
            brid = myinsert_with_cursor(cur,'brainRegion',{'name': name})
        else:
            brid = res[0]
        myinsert_with_cursor(cur,'brainRegion_neuron',{'brainRegionLevel': level, 'brainRegionId': brid,'neuronId': neuron_id})

@myconnect
def insertcelltypes(conn,celllist,neuron_id):
    # inserts a region by checking if exists in region table and then in the connecting table 
    #typelabels = ['class1','class2','class3','class3B','class3C']
    cur = conn.cursor(buffered=True)
    level = 0
    for item in celllist:
        level += 1
        name = escapechars(item[1])
        statement = "select id from cellType where name = '{}'".format(name)
        cur.execute(statement)
        res = cur.fetchone()  
        if res is None:
            brid = myinsert_with_cursor(cur,'cellType',{'name': name})
        else:
            brid = res[0]
        myinsert_with_cursor(cur,'cellType_neuron',{'cellTypeLevel': level, 'cellTypeId': brid,'neuronId': neuron_id})

def insertdeposition(oldid,adict):
    now = datetime.now()
    dt_string = now.strftime("%Y-%m-%d %H:%M:%S")
    data = {'neuron_id': oldid,
        'neuron_name': adict['name'],
        'deposition_date': adict['depositiondate'],
        'upload_date': dt_string}
    myinsert('deposition',data)

@pgconnect
def inserttissueshrinkage(conn,neuron_id,oldid):
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    stmt = """SELECT name, shrinkage, reported_value, reported_xy, reported_z, corrected_value, corrected_xy, corrected_z 
    FROM neuron,shrinkagevalue 
    WHERE neuron.shrinkagevalue_id = shrinkagevalue.id and neuron.id = {} """.format(neuron_id)
    cur.execute(stmt)
    res = cur.fetchone()
    typedict = {"reported and corrected": 1,
        "reported and not corrected": 2,
        "Not reported": 3,
        "not applicable": 4,
        "Not applicable": 4}
    repdict = {"reported and corrected": 'Reported',
        "reported and not corrected": 'Reported',
        "Not reported": 'Not reported',
        "not applicable": "Not applicable",
        "Not applicable": "Not applicable"}
    corrdict = {"reported and corrected": 'Corrected',
        "reported and not corrected": 'Not corrected',
        "Not reported": '',
        "not applicable": '',
        "Not applicable": ''}
    data = {'neuron_name': res['name'],
        'shrinkage_reported': repdict[res['shrinkage']],
        'shrinkage_corrected': corrdict[res['shrinkage']],
        'reported_value': res['reported_value'],
        'reported_xy': res['reported_xy'],
        'reported_z': res['reported_z'],
        'corrected_value': res['corrected_value'],
        'corrected_xy': res['corrected_xy'],
        'corrected_z': res['corrected_z'],
        'shrinkage_type_id': typedict[res['shrinkage']],
        'neuron_id': oldid
    }
    myinsert('Tissue_shrinkage',data)

@pgconnect
def insertcompleteness(conn,neuron_id,oldid,adict):
    cur = conn.cursor()
    stmt = "SELECT completeness, domain, morph_attributes FROM neuron_structure WHERE neuron_id = {}".format(neuron_id)
    cur.execute(stmt)
    res = cur.fetchall()
    morph_attr = res[0][2]
    dcompl = {item[1]: item[0] for item in res}
    #decide domain 
    data = {}
    
    dkeys = dcompl.keys()
    has_soma = adict['has_soma']
    cdict = {'Complete':2, 'Moderate': 1, 'Incomplete':0}
    combdict = {'Complete':{'Complete': 7, 'Moderate': 6, 'Incomplete': 5},
        'Moderate':{'Complete': 8, 'Moderate': 4, 'Incomplete': 3},
        'Incomplete':{'Complete': 14, 'Moderate': 1, 'Incomplete':13},
    }
    data = {'PMID': adict['publication_pmid'],
        'domain_id': 0,
        'den_integrity_id': -1,
        'ax_integrity_id': -1,
        'den_ax_integrity_id': -1,
        'attributes_id': 3,
        'curated': 1,
        'neu_integrity_id': -1,
        'pr_integrity_id': -1
    }
    if 'NEU' in dkeys:
        data['neu_integrity_id'] = cdict[dcompl['NEU']]
        if has_soma:
            data['domain_id'] = 9
        else:
            data['domain_id']  = 8
    elif 'PR' in dkeys:
        data['pr_integrity_id'] = cdict[dcompl['PR']]
        if has_soma:
            data['domain_id']  = 11
        else:
            data['domain_id']  = 10
    elif 'AP' in dkeys or 'BS' in dkeys:
        if 'AP' in dkeys:
            data['den_integrity_id'] = cdict[dcompl['AP']]
            if 'AX' in dkeys:
                data['den_ax_integrity_id'] = combdict[dcompl['AP']][dcompl['AX']]
        else:
            data['den_integrity_id'] = cdict[dcompl['BS']]
            if 'AX' in dkeys:
                data['den_ax_integrity_id'] = combdict[dcompl['BS']][dcompl['AX']]
        if 'AX' in dkeys:
            data['ax_integrity_id'] = cdict[dcompl['AX']]
            if has_soma:
                data['domain_id']  = 7
            else:
                data['domain_id']  = 5
        else:
            if has_soma:
                data['domain_id']  = 6
            else:
                data['domain_id']  = 4
    else:
        #only axon
        data['ax_integrity_id'] = cdict[dcompl['AX']]
        if has_soma:
            data['domain_id']  = 3
        else:
            data['domain_id']  = 1
    data['attributes_id'] = morph_attr
    data['neuron_id'] = oldid
    myinsert('neuron_completeness',data)
        


@pgconnect
def exportmeasurements(conn,neuron_id,oldid,neuron_name):
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    stmt = "select measurements.* from measurements,neuron where neuron.id = {} AND neuron.summary_meas_id = measurements.id".format(neuron_id)
    cur.execute(stmt)
    res = cur.fetchone()
    res2 = {item[0].upper() + item[1:]: res[item] for item in res.keys()}
    del res2['Id']
    res2['Neuron_name'] = neuron_name 
    res2['neuron_id'] = oldid
    myinsert('measurements',res2)
    stmt = """select measurements.*,neuron_structure.domain from measurements
    INNER JOIN neuron_structure 
    ON measurements.id = neuron_structure.measurements_id 
    where neuron_structure.neuron_id = {}""".format(neuron_id)
    cur.execute(stmt)
    res = cur.fetchall()

    for meas in res:
        res2 = {item[0].upper() + item[1:]: meas[item] for item in meas.keys()}
        domain = res2.pop('Domain')
        del res2['Id']
        res2['Neuron_name'] = neuron_name 
        res2['neuron_id'] = oldid
        myinsert('measurements{}'.format(domain),res2)

@pgconnect
def exportdetailedmeasurements(conn,neuron_id,oldid,neuron_name):
    """
    Loop over detailed measurements and export depending on type. If result is null, export null.
    """
    detailedtypes = ['AP','APA','APB','AX','BS','BSA','NEU','PR']
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    for atype in detailedtypes:
        stmt = """select measurements.* from measurements,neuron_structure where neuron_structure.neuron_id = {}
        AND neuron_structure.domain = '{}' 
        AND neuron_structure.measurements_id = measurements.id""".format(neuron_id,atype)
        cur.execute(stmt)
        res = cur.fetchone()
        tablename= 'measurements{}'.format(atype)
        if res is None:
            # insert empty result in table
            myinsert(tablename,{
                'Neuron_name': neuron_name,
                'neuron_id': oldid
            })
        else:
            res2 = {item[0].upper() + item[1:]: res[item] for item in res.keys()}
            del res2['Id']
            res2['Neuron_name'] = neuron_name 
            res2['neuron_id'] = oldid
            myinsert(tablename,res2)
        #TODO fetch deatailed measurments from measurements table and import
        # stmt = """select measurements.*,neuron_structure.domain from measurements
        # INNER JOIN neuron_structure 
        # ON measurements.id = neuron_structure.measurements_id 
        # where neuron_structure.neuron_id = {}""".format(neuron_id)
        # cur.execute(stmt)
        # res = cur.fetchall()

        # for meas in res:
        #     res2 = {item[0].upper() + item[1:]: meas[item] for item in meas.keys()}
        #     domain = res2.pop('Domain')
        #     del res2['Id']
        #     res2['Neuron_name'] = neuron_name 
        #     res2['neuron_id'] = oldid
        #     myinsert('measurements{}'.format(domain),res2)
        



@pgconnect
def getrowasdict(conn,table,id):
    statement = """
    SELECT column_name
    FROM information_schema.columns
    WHERE table_schema = 'public'
    AND table_name   = '{}'""".format(table)
    cur = conn.cursor()
    cur.execute(statement)
    result = cur.fetchall()
    cols = [item[0] for item in result]
    statement = "SELECT {} from {} where {}.id = {}".format(','.join(cols),table,table,id)
    cur.execute(statement)
    result = cur.fetchone()
    if result is None:
        return None
    else:
        #resdict =  dict(zip(cols,result))
        resdict =  {table + '_' + key: val for key,val in zip(cols,result)}
        return resdict

@pgconnect
def getmyregions(conn,path):
    if path is not None:
        statement = "select name from region where path @> '{}' order by path".format(path)
        cur = conn.cursor()
        cur.execute(statement)
        res = cur.fetchall()
    else:
        res = []
    result = {}
    regionlabels = ['region1','region2','region3','region3B']
    defaultval = ['Not reported'] * 4
    if len(regionlabels) < len(res):
        lendiff = len(res) - len(regionlabels)
        regionlabels = regionlabels + ['region3B'] * lendiff
        defaultval = defaultval + ['Not reported'] * lendiff
    result = [[a,b] for a,b in zip(regionlabels,defaultval)]
    
    for ix in range(len(res)):
        result[ix][1] = res[ix][0]
    
    resultdict = {item[0]: item[1] for item in result if item[0 != 'region3B']}
    if len(res) > 3:
        resultdict['region3B'] = res[3][0]

    return { "regionlabels": result,**resultdict}

@pgconnect
def getmycelltypes(conn,path):
    if path is not None:
        statement = "select name from celltype where path @> '{}' order by path".format(path)
        cur = conn.cursor()
        cur.execute(statement)
        res = cur.fetchall()
    else:
        res = []
    result = {}
    typelabels = ['class1','class2','class3','class3B','class3C']
    defaultval = ['Not reported'] * 5
    if len(typelabels) < len(res):
        lendiff = len(res) - len(typelabels)
        typelabels = typelabels + ['class3C'] * lendiff
        defaultval = defaultval + ['Not reported'] * lendiff
    result = [[a,b] for a,b in zip(typelabels,defaultval)]
    for ix in range(len(res)):
        result[ix][1] = res[ix][0]
    resultdict = {item[0]: item[1] for item in result if item[0 != 'class3C']}
    if len(res) > 4:
        resultdict['class3C'] = res[4][0]

    return { "celltypelabels": result,**resultdict}

@pgconnect
def tweetneuron(conn,neuron_name,archive):
    statement = "update ingested_archives SET neurontotweet = '{}' where name = '{}'".format(neuron_name,archive)
    cur = conn.cursor()	 
    logging.info(conn)
    logging.info(cur)
    cur.execute(statement)
    return {"result": "success"}

# @myconnect
# def insertbrainregions(conn,neuron_id,:
#     # checks if region exists at specified level
#     cur = conn.cursor()
#     statement = """SELECT 
#     DISTINCT brainRegion_neuron.brainRegionId, 
#     brainRegion_neuron.brainRegionLevel, 
#     brainRegion.name, 
#     brainRegion_neuron.brainRegionLevel 
#     FROM 
#         brainRegion_neuron 
#     INNER JOIN 
#         brainRegion 
#     ON 
#         ( 
#             brainRegion_neuron.brainRegionId = brainRegion.id) 
#     WHERE 
#         brainRegion_neuron.brainRegionLevel = {} 
#     AND brainRegion.name = '{}';""".format(level,name)
#     cur.exexute(statement)
#     res = cur.fetchall()
#     return len(res) > 0

""" @pgconnect
def getregionname(conn,path):
    cur = conn.cursor()
    stmt = "select name from region where path = '{}'".format(path)
    cur.execute(stmt)
    res = cur.fetchone()
    return res[0] """

""" def checkregion(path):
    # checks if Region at level as indicated by path
    # if not, inserts item and then checks parent path by recursive call
    # if so, checks parents to see if they are the same by recursive call
    patharr = path.split('.')
    level = len(patharr)
    name = getregionname(path)
    if checkreglvl(name,level):
        insertregion
    if level !=1:
        checkregion('.'.join(patharr[0:-1])) """

@pgconnect
def getneuronsforexport(conn,neuronclause = ''):
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    stmt = """SELECT neuron.*
    FROM 
        neuron 
    INNER JOIN 
        export 
    ON 
        ( 
            export.neuron_id = neuron.id) 
    WHERE 
        (export.status = 'ready' OR export.status = 'error'{})""".format(neuronclause)
    cur.execute(stmt)
    res = cur.fetchall()
    return res

@pgconnect
def getneuronforexport(conn,neuron_name):
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    stmt = """SELECT neuron.*
    FROM 
        neuron 
    WHERE 
        neuron.name = '{}'""".format(neuron_name.replace("'","''"))
    cur.execute(stmt)
    res = cur.fetchall()
    return res


def getneurondata(neuron_name):
    alist = getneuronforexport(neuron_name)
    item = alist[0]
    archive_id = item['archive_id']
    item = {**item, **getrowasdict('archive',archive_id)}

    region_id = item['region_id']
    if region_id is None:
        item = {**item, **{'region_path': None}}
    else:
        item = {**item, **getrowasdict('region',region_id)}
    item = {**item, **getmyregions(item['region_path'])}

    celltype_id = item['celltype_id']
    if celltype_id is None:
        item = {**item, **{'celltype_path': None}}
    else:
        item = {**item, **getrowasdict('celltype',celltype_id)}
    item = {**item, **getmycelltypes(item['celltype_path'])}

    publication_id = item['publication_id']
    item = {**item, **getrowasdict('publication',publication_id)}

    expcond_id = item['expcond_id']
    item = {**item, **getrowasdict('expcond',expcond_id)}

    summary_meas_id = item['summary_meas_id']
    item = {**item, **getrowasdict('measurements',summary_meas_id)}

    originalformat_id = item['originalformat_id']
    item = {**item, **getrowasdict('originalformat',originalformat_id)}

    staining_id = item['staining_id']
    item = {**item, **getrowasdict('staining',staining_id)}

    shrinkagevalue_id = item['shrinkagevalue_id']
    item = {**item, **getrowasdict('shrinkagevalue',shrinkagevalue_id)}

    strain_id = item['strain_id']
    item = {**item, **getrowasdict('strain',strain_id)}

    species_id = item['strain_species_id']
    item = {**item, **getrowasdict('species',species_id)}

    expcond_id = item['expcond_id']
    item = {**item, **getrowasdict('expcond',expcond_id)}
    
    return item

def getallreadydata():
    # gets all ready neurons
    # prepares full dict for neuron, including measurements, shrinkage, region  pvec
    neurons = getneuronsforexport()

    result = []
    for item in neurons:
        archive_id = item['archive_id']
        item = {**item, **getrowasdict('archive',archive_id)}

        region_id = item['region_id']
        item = {**item, **getrowasdict('region',region_id)}
        item = {**item, **getmyregions(item['region_path'])}

        celltype_id = item['celltype_id']
        item = {**item, **getrowasdict('celltype',celltype_id)}
        item = {**item, **getmycelltypes(item['celltype_path'])}

        publication_id = item['publication_id']
        item = {**item, **getrowasdict('publication',publication_id)}

        expcond_id = item['expcond_id']
        item = {**item, **getrowasdict('expcond',expcond_id)}

        summary_meas_id = item['summary_meas_id']
        item = {**item, **getrowasdict('measurements',summary_meas_id)}

        originalformat_id = item['originalformat_id']
        item = {**item, **getrowasdict('originalformat',originalformat_id)}

        staining_id = item['staining_id']
        item = {**item, **getrowasdict('staining',staining_id)}

        shrinkagevalue_id = item['shrinkagevalue_id']
        item = {**item, **getrowasdict('shrinkagevalue',shrinkagevalue_id)}

        strain_id = item['strain_id']
        item = {**item, **getrowasdict('strain',strain_id)}

        species_id = item['strain_species_id']
        item = {**item, **getrowasdict('species',species_id)}

        expcond_id = item['expcond_id']
        item = {**item, **getrowasdict('expcond',expcond_id)}
        
        result.append(item)
    return result

def cleanstr(astring):
    if astring[0] == " ":
        astring = astring[1:]
    astring = astring.replace(' ','_')
    return "".join([c for c in astring if c.isalpha() or c.isdigit() or c == '_']).rstrip()

def cleanerr(astring):
    return "".join([c for c in astring if c.isalpha() or c.isdigit() or c == '_' or c == ' ']).rstrip()

def cleanval(astring):
    return astring.replace(',','')

def connect():  
    conn = psycopg2.connect(
        host=cfg.pg_host,
        port=cfg.pg_port,
        database=cfg.pg_database,
        user=cfg.pg_user,
        password=cfg.pg_password,
    )
    conn.autocommit = True
    return conn

@pgconnect
def insert(conn,tablename,data):
    # takes data with fields as keys in dictionary, data as values
    cur = conn.cursor()
    # clean 'NULL' Values
    values = ''
    data = {item: data[item] for item in data if data[item] is not None } 
    data = {item: data[item] for item in data if data[item] != 'NULL'}
    
        
    for item in data:
        if isinstance(data[item],str):
            values += "'{}',".format(data[item].replace("'","''"))
        else:
            values += str(data[item]) + ','
    values = values[:-1]
    
    fields = ",".join(data.keys())
    if len(data) == 0:
        statement = "INSERT INTO {}(id) VALUES(DEFAULT)".format(tablename)
    else:
        statement = """INSERT INTO {}({}) VALUES ({}) """.format(tablename,fields,values)
    cur.execute(statement)  
    cur.execute("SELECT currval(pg_get_serial_sequence('{}','id'))".format(tablename))
    result = cur.fetchone()
    inserted_id = result[0]
    conn.close()
    return inserted_id

@myconnect
def myinsert(conn,tablename,data):
    # takes data with fields as keys in dictionary, data as values
    cur = conn.cursor()
    data = {item: data[item] for item in data if data[item] is not None}
    fields = ",".join(data.keys())
    values = "','".join([str(item).replace("'","''") for item in data.values()])
    statement = """INSERT INTO {}({}) VALUES ('{}') """.format(tablename,fields,values)
    _execute_mysql_with_retry(cur, statement)
    cur.execute("select LAST_INSERT_ID()")
    result = cur.fetchone()
    inserted_id = result[0]
    return inserted_id


@myconnect
def myneuronexists(conn, neuron_name):
    cur = conn.cursor()
    stmt = "SELECT neuron_id FROM neuron WHERE neuron_name = '{}' LIMIT 1".format(neuron_name.replace("'","''"))
    cur.execute(stmt)
    return cur.fetchone() is not None

@pgconnect
def updateneuronstatus(conn,neuron_name, status,message = ''):
    cur = conn.cursor()
    stmt = "UPDATE ingestion set status = '{}', message = '{}' where neuron_name = '{}'".format(status,message,neuron_name.replace("'","''"))
    cur.execute(stmt)

@pgconnect
def isindb(conn,tablename, column, value):
    # check if value in table of specified column is in db
    value = value.replace("'","''")
    cur = conn.cursor()
    statement = "SELECT {} FROM {} where {} = '{}'".format(column,tablename,column,value)
    try:
        cur.execute(statement)
    except Exception as e:
        print(e)
    result = cur.fetchone()
    return result is not None

def stq(tocheck):
    if isinstance(tocheck,str):
        return "'{}'".format(tocheck)
    else: 
        return str(tocheck)

@pgconnect
def update(conn,tablename,whereq,updateq):
    """ Updates table with rows matching whereq to values of updateq
    Returns numbers of rows affected, -1 if none
    """
    wclause = " AND ".join([item + " = " + stq(whereq[item]) for item in whereq])
    uclause = ", ".join([item + " = " + stq(updateq[item]) for item in updateq])
    cur = conn.cursor()
    statement = "UPDATE {} SET {} WHERE {}".format(tablename,uclause,wclause)
    cur.execute(statement)
    return cur.rowcount

def ingestneuron(d):
    #inserts one neuron with values from dictionary d
    # TODO add parameters. 
    nonechecks= ['min_weight','max_weight']
    for item in nonechecks:
        if d[item] == 'Not reported': 
            d[item] = 'NULL'
    if d['shrinkval_id'] == 0:
        d['shrinkval_id'] = "NULL"
    if d['max_age'] == 'Not reported' or d['max_age'] is None:
        d['max_age'] = "NULL"
    if d['min_age'] == "Not reported" or d['min_age'] is None:
        d['min_age'] = "NULL"
    if d['URL_reference'] is None:
        d['URL_reference'] = " "
    else:
        d['URL_reference']  = "'{}'".format(d['URL_reference'])

    if not isinstance(d['note'],str):
        notetext = ""
    else:
        notetext = d['note'].encode('ascii', 'xmlcharrefreplace').decode()
        notetext = notetext.replace("'","''")
    
    if not isinstance(d['protocol'],str):
        d['protocol'] = 'Not reported'

    if not isinstance(d['expercond'],str):
        expcondtext = ""
    else:
        expcondtext = d['expercond'].encode('ascii', 'xmlcharrefreplace').decode()
        expcondtext = expcondtext.replace("'","''")

    if not isinstance(d['age_classification'],str):
        d['age_classification'] = "Not reported"

    if not isinstance(d['shrinkage_reported'],str):
        d['shrinkage_reported'] = "Not reported"

    for item in d:
        if isinstance(d[item],str):
            d[item] = escapechars(d[item])
            d[item] = d[item].replace("'","''")

    checkexists_cached('archive', 'archive_name', {'archive_name': d['archive']})
    conn=connect()
    cur = conn.cursor()
    statement = """CALL ingest_data('{}', '{}', '{}',  '{}', '{}','{}' , '{}' , '{}','{}', '{}','{}','{}', '{}','{}', '{}', '{}', '{}', '{}', cast({} as boolean), '{}' , '{}' , '{}', {}, {},{},{}, '{}', '{}','{}', '{}', {},'{}','{}',  null)""".format(d['neuron_name'].replace("'","''"),d['archive'],d['URL_reference'],d['species'], expcondtext,d['age_classification'],d['region'],d['celltype'],d['deposition_date'],d['uploaddate'],
     d['magnification'],d['objective'],d['format'],d['protocol'],d['slice_direction'],str(d['thickness']),d['stain'],d['strain'],
     str(d['has_soma']),d['shrinkage_reported'],d['age_scale'],d['gender'],str(d['max_age']),str(d['min_age']),d['min_weight'],
     d['max_weight'],notetext.replace("'","''"),str(d['pmid']),d['doi'],str(d['sum_mes_id']),str(d['shrinkval_id']),d['reconstruction'],d['URL_reference'])
    cur.execute(statement)
    result = cur.fetchone()
    neuron_id = result[0]
    conn.close()
    return neuron_id

def getarticleid(pmid,doi):
    """ Gets the article id for insertion.
    """
    cache_key = (cfg.dbsel, str(pmid), str(doi or ''))
    with _publication_lock:
        if cache_key in _publication_cache:
            return _publication_cache[cache_key]
        conn = mysc.connect(
            user=cfg.dbuser,
            password=cfg.dbpass,
            host=cfg.dbhost,
            database=cfg.dbsel,
            auth_plugin=cfg.db_auth_plugin,
        )
        conn.autocommit = True
        cur = conn.cursor()
        try:
            if doi is not None:
                isref = validators.url(doi)
            else:
                isref = False
            if pmid > 0:
                stmt = "SELECT DISTINCT article_id,PMID FROM neuron_article where PMID = {}".format(pmid)
            else:
                if isref:
                    stmt = "SELECT DISTINCT reference_article.article_id, neuron_article.PMID FROM reference_article,neuron_article where neuron_article.article_id = reference_article.article_id AND reference_article.article_URL = '{}'".format(doi)
                else:
                    stmt = "SELECT DISTINCT article_id, neuron_article.PMID FROM neuron_article, AllPublications where neuron_article.PMID = AllPublications.PMID AND AllPublications.DOI = '{}'".format(doi)
            cur.execute(stmt)
            res = cur.fetchone()
            if res is not None:
                result = (res[0],res[1])
                _publication_cache[cache_key] = result
                return result

            if pmid > 0:
                pmrecord = io.fetchpmarticle(str(pmid))
            else:
                
                if isref:
                    pmrecord = io.fetchurlreference(doi)
                    stmt = 'SELECT MAX(PMID) FROM AllPublications'
                    cur.execute(stmt)
                    res = cur.fetchone()
                    pmid = max(res[0]+1,100000000)
                else:
                    stmt = 'SELECT MIN(PMID) FROM AllPublications'
                    cur.execute(stmt)
                    res = cur.fetchone()
                    pmid = res[0]-1
                    pmrecord = io.fetchdoiarticle(doi)
            stmt = 'SELECT PMID FROM AllPublications where PMID = {}'.format(pmid)
            cur.execute(stmt)
            res = cur.fetchone()
            if res is None:
                now = datetime.now()
                dt_string = now.strftime("%Y-%m-%d %H:%M:%S")
                pubrec = {
                    'PMID': pmid,
                    'DOI': pmrecord['doi'],
                    'Year': pmrecord['year'],
                    'Journal': pmrecord['journal'],
                    'Paper_Title': pmrecord['article_title'],
                    'First_Author': pmrecord['first_author'],
                    'Last_Author': pmrecord['last_author'],
                    'OCDate': dt_string,
                    'Data_Status': 'In the repository'
                }
                if isref:
                    del pubrec['DOI']
                myinsert('AllPublications', pubrec)
            refrec = pmrecord
            del refrec["first_author"] 
            del refrec["last_author"] 
            del refrec["journal"] 
            del refrec["doi"] 
            del refrec["year"]
            
            res = myinsert('reference_article',refrec)

            result = (res,pmid)
            _publication_cache[cache_key] = result
            return result
        finally:
            conn.close()


@pgconnect
def exportpublication(conn,oldid,neuron_id):
    """ Check if exists in neuron_article table. If so, select article id
    If not, check max. Increment article id and insert. Otherwise, insert with existing article id.
    """
    
    cur = conn.cursor()
    stmt = """SELECT publication.pmid,publication.doi from publication,neuron 
        WHERE neuron.publication_id = publication.id
        AND neuron.id={}""".format(neuron_id)
    cur.execute(stmt)
    res = cur.fetchone()
    pmid = res[0]
    doi = res[1]
    
    (article_id, newpmid) = getarticleid(pmid,doi)

    myinsert('neuron_article',{
        'neuron_id': oldid,
        'article_id': article_id,
        'PMID': newpmid
    })


@pgconnect
def getnneurons(conn,foldername):
    archive_name = io.namefromfolder(foldername)
    cur = conn.cursor()
    stmt = """
    SELECT 
    COUNT(public.neuron.id) AS nneurons, 
    public.archive.name 
FROM 
    public.neuron 
INNER JOIN 
    public.archive 
ON 
    ( 
        public.neuron.archive_id = public.archive.id) 
WHERE 
    public.archive.name = '{}' 
GROUP BY 
    public.archive.name""".format(archive_name)
    cur.execute(stmt)
    res = cur.fetchone()
    if res is None:
        return 0
    else:
        return res[0]

@pgconnect
def deleteneuron(conn,neuronname):
    """
    Delete neuron from project DB
    """
    cur = conn.cursor()
    stmt = "delete from ingestion where neuron_name='{}'".format(neuronname)
    cur.execute(stmt)
    stmt = "delete from neuron where name='{}'".format(neuronname)
    cur.execute(stmt)

@pgconnect
def archiveneuron(conn,neuronname):
    """
    Delete neuron from ingestion table in project DB
    """
    cur = conn.cursor()
    stmt = "delete from ingestion where neuron_name='{}'".format(neuronname)
    cur.execute(stmt)

@myconnect
def deletemyneuron(conn,neuronname):
    """
    Delete neuron from release DB
    """
    cur = conn.cursor()
    stmt = "delete from neuron where neuron_name='{}'".format(neuronname)
    cur.execute(stmt)


@myconnect
def deletemyarchive(conn,archive_name):
    """
    Delete archive from release DB after its neurons are removed.
    """
    cur = conn.cursor()
    stmt = "delete from archive where archive_name='{}'".format(archive_name)
    cur.execute(stmt)

@myconnect
def deletemyarchivecascade(conn, archive_name):
    cur = conn.cursor()
    cur.execute("SELECT archive_id FROM archive WHERE archive_name='{}'".format(archive_name))
    archive_rows = cur.fetchall()
    archive_ids = [str(item[0]) for item in archive_rows]
    if not archive_ids:
        return

    cur.execute("SELECT neuron_id FROM neuron WHERE archive_id IN ({})".format(",".join(archive_ids)))
    neuron_ids = [str(item[0]) for item in cur.fetchall()]

    if neuron_ids:
        id_list = ",".join(neuron_ids)
        dependent_tables = [
            'api_integrity',
            'api_neuron',
            'brainRegion_neuron',
            'cellType_neuron',
            'celltype_table',
            'deposition',
            'DOMAINTEMP',
            'export_neuron',
            'file',
            'GenerateReport_Groups',
            'measurements',
            'measurementsAP',
            'measurementsAPA',
            'measurementsAPB',
            'measurementsAX',
            'measurementsBS',
            'measurementsBSA',
            'measurementsNEU',
            'measurementsPR',
            'neuron_article',
            'neuron_auxdata',
            'neuron_completeness',
            'neuron_expercond',
            'neuron_intermed',
            'neuron_multiple',
            'nif_neuron',
            'persistance_vector',
            'temp_export',
            'Tissue_shrinkage',
        ]

        cur.execute(
            """
            SELECT TABLE_NAME
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_TYPE = 'BASE TABLE'
            AND TABLE_NAME IN ({})
            """.format(",".join(["'{}'".format(table) for table in dependent_tables]))
        )
        base_tables = set(item[0] for item in cur.fetchall())

        cur.execute(
            """
            SELECT TABLE_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            AND COLUMN_NAME = 'neuron_id'
            AND TABLE_NAME IN ({})
            """.format(",".join(["'{}'".format(table) for table in dependent_tables]))
        )
        tables_with_neuron_id = set(item[0] for item in cur.fetchall())

        for table in dependent_tables:
            if table not in base_tables or table not in tables_with_neuron_id:
                continue
            cur.execute("DELETE FROM {} WHERE neuron_id IN ({})".format(table, id_list))

        cur.execute("DELETE FROM neuron WHERE neuron_id IN ({})".format(id_list))

    cur.execute("DELETE FROM archive WHERE archive_id IN ({})".format(",".join(archive_ids)))


@myconnect
def cleanupmyarchiveextras(conn, neuronarr):
    if not neuronarr:
        return

    quoted_names = "','".join(neuronarr)

    cur = conn.cursor()
    stmt = "SELECT neuron_id FROM deposition WHERE neuron_name IN ('{}')".format(quoted_names)
    cur.execute(stmt)
    neuron_ids = [str(item[0]) for item in cur.fetchall()]

    if neuron_ids:
        id_list = ",".join(neuron_ids)
        cur.execute("DELETE FROM persistance_vector WHERE neuron_id IN ({})".format(id_list))
        cur.execute("DELETE FROM Tissue_shrinkage WHERE neuron_id IN ({})".format(id_list))

    cur.execute("SELECT DISTINCT article_id, PMID FROM neuron_article WHERE neuron_id IN ({})".format(",".join(neuron_ids) if neuron_ids else "0"))
    article_rows = cur.fetchall()
    article_ids = [str(item[0]) for item in article_rows if item[0] is not None]
    pmids = [str(item[1]) for item in article_rows if item[1] is not None]

    if article_ids:
        cur.execute(
            "DELETE FROM reference_article WHERE article_id IN ({}) AND article_id NOT IN (SELECT article_id FROM neuron_article)".format(
                ",".join(article_ids)
            )
        )
    if pmids:
        cur.execute(
            "DELETE FROM AllPublications WHERE PMID IN ({}) AND PMID NOT IN (SELECT PMID FROM neuron_article WHERE PMID IS NOT NULL)".format(
                ",".join(pmids)
            )
        )


@pgconnect
def getpvecmes(conn,neuron_id):
    def zeroifnone(a):
        if a is None:
            return 0 
        else:
            return a
    # produces vector of pvec + summary measurements (length 121) for duplicate detection
    cur = conn.cursor()
    stmt = "select summary_meas_id from neuron where id={}".format(neuron_id)
    cur.execute(stmt)
    mesid = cur.fetchone()[0]
    stmt = "SELECT * from measurements where id ={}".format(mesid)
    cur.execute(stmt)
    measurements = list(cur.fetchone())[1:]
    measurements = [zeroifnone(item) for item in measurements]
    stmt = "select coeffs from pvec where neuron_id={}".format(neuron_id)
    cur.execute(stmt)
    res = cur.fetchone()
    persistence = res[0]

    return (measurements,persistence)
    
    

@pgconnect
def ingestdomain(conn,neuron_id,domains,morph_attr,detmeas_ids):
    cur = conn.cursor()
    if "Soma" in domains:
        del domains["Soma"]
    for key in domains:
        stmt = "INSERT INTO neuron_structure (neuron_id, completeness, domain,morph_attributes,measurements_id) VALUES ({},'{}','{}',{},{})".format(neuron_id,domains[key],key,morph_attr,detmeas_ids[key])
        cur.execute(stmt)

@myconnect
def checkindb(conn,table,indexfield, fields):
    for item in fields:
        #if isinstance(fields[item],str):
        #    fields[item] = escapechars(fields[item])
        if fields[item] == None:
            fields[item] = 'Not reported'
        if isinstance(fields[item],float) or isinstance(fields[item],int):
            fields[item] = str(fields[item])
    cur = conn.cursor()
    cur.execute("SELECT * from {} where {} = '{}'".format(table,indexfield,fields[indexfield]))
    res = cur.fetchone()
    #logging.info("cur.fetchone: {}".format(res))
    return res

def checkindb_in_db(table, indexfield, fields, database):
    fields = dict(fields)
    for k, v in fields.items():
        if v is None:
            fields[k] = 'Not reported'
        elif isinstance(v, (float, int)):
            fields[k] = str(v)

    # Connect to the database
    conn = mysc.connect(
        user=cfg.dbuser,
        password=cfg.dbpass,
        host=cfg.dbhost,
        database=database,
        auth_plugin=cfg.db_auth_plugin,
    )
    conn.autocommit = True

    try:
        cur = conn.cursor()
        # Use parameterized query to avoid SQL injection
        query = f"SELECT * FROM {table} WHERE {indexfield} = %s"
        cur.execute(query, (fields[indexfield],))
        res = cur.fetchone()
        return res
    finally:
        conn.close()


@myconnect
def checkexists(conn,table,indexfield, fields):
    #replace single quotes with two sq
    for item in fields:
        if isinstance(fields[item],str):
            fields[item] = fields[item].replace("'","''")
    res = checkindb(table,indexfield,fields)
    cur = conn.cursor()
    if res is None:
        stmt = "insert into {} ({}) values ({})".format(table,','.join(fields.keys()),"'" + "','".join(fields.values()) + "'")
        try:
            _execute_mysql_with_retry(cur, stmt)
            cur.execute('select LAST_INSERT_ID()')
            res = cur.fetchone()
        except mysc.IntegrityError as exc:
            if not _is_duplicate_error(exc):
                raise
            res = checkindb(table,indexfield,fields)
            if res is None:
                raise
    return res[0]

def ingestregion(adict):
    # Checks dict for region fields
    # Wraps fields into array string for postgres stored procedure
    proceed = True

    reg1 = adict.get('region1','')
    if reg1 == 'Not reported' or reg1 == '':

        raise Exception('Region 1 must have value')
    else:
        pgarr = "array['{}'".format(reg1.replace("'","''").strip())
        path = cleanstr(reg1)
    reg2 = adict.get('region2','')
    if reg2 == 'Not reported' or reg2 == '':
        proceed = False
    else:
        pgarr += ",'{}'".format(reg2.replace("'","''").strip())
        path += '.' + cleanstr(reg2)
    reg3 = adict.get('region3','')
    if reg3 == 'Not reported' or reg3 == '' and proceed:
        proceed = False
    elif proceed:
        path += '.' + cleanstr(reg3)
        pgarr += ",'{}'".format(reg3.replace("'","''").strip())
    reg3B = adict.get('region3B','')
    if reg3B == 'Not reported' or reg3B == '' and proceed:
        pass        
    elif proceed:
        regarr = reg3B.split(',')
        for item in regarr:
            pgarr += ",'{}'".format(cleanval(item.replace("'","''").strip()))
            path += '.' + cleanstr(item)
    pgarr += "]"
    cache_key = (cfg.pg_database, path, pgarr)
    with _pg_reference_lock:
        if cache_key in _pg_region_cache:
            return _pg_region_cache[cache_key]
        conn=connect()
        try:
            cur = conn.cursor()
            cur.execute("CALL ingest_region({},'{}')".format(pgarr,path)) #TODO check if paranthesis should be here
            cur.execute("SELECT id from region where path = '{}';".format(path))
            theid = cur.fetchone()
            _pg_region_cache[cache_key] = theid[0]
            return theid[0]
        finally:
            conn.close()
    # Strips invalid characters from path elements string.
    # Concatenates path elements into ltree path
    # Calls stored procedure to ingest region at lowest level if needed
    # Regions at level 3A,B, C are ingested at same level in tree by calling procedure for each 


def ingestcelltype(adict):
    # Checks dict for celltype fields
    # Wraps fields into array string for postgres stored procedure
    proceed = True

    reg1 = adict.get('class1','')
    if reg1 == 'Not reported' or reg1 == '':
        #raise Exception('class 1 must have value')
        return 0
    else:
        pgarr = "array['{}'".format(reg1)
        path = cleanstr(reg1.replace("'","''").strip())
    reg2 = adict.get('class2','')
    if reg2 == 'Not reported' or reg2 == '':
        proceed = False
    else:
        pgarr += ",'{}'".format(reg2)
        path += '.' + cleanstr(reg2.replace("'","''").strip())
    reg3 = adict.get('class3','')
    if reg3 == 'Not reported'  or reg3 == '' and proceed:
        proceed = False
    elif proceed:
        path += '.' + cleanstr(reg3)
        pgarr += ",'{}'".format(reg3.replace("'","''").strip())
    reg3B = adict.get('class3B','')
    if reg3B == 'Not reported'  or reg3B == '' and proceed:
        proceed = False
    elif proceed:
        path += '.' + cleanstr(reg3B)
        pgarr += ",'{}'".format(reg3B.replace("'","''").strip())
    reg3C = adict.get('class3C','')
    if reg3C == 'Not reported' or reg3C == '' and proceed:
        pass        
    elif proceed:
        regarr = reg3C.split(',')
        for item in regarr:
            pgarr += ",'{}'".format(item.replace("'","''").strip())
            path += '.' + cleanstr(item)
    pgarr += "]"
    cache_key = (cfg.pg_database, path, pgarr)
    with _pg_reference_lock:
        if cache_key in _pg_celltype_cache:
            return _pg_celltype_cache[cache_key]
        conn=connect()
        try:
            cur = conn.cursor()
            cur.execute("CALL ingest_celltype({},'{}')".format(pgarr,path))
            cur.execute("SELECT id from celltype where path = '{}';".format(path))
            theid = cur.fetchone()
            _pg_celltype_cache[cache_key] = theid[0]
            return theid[0]
        finally:
            conn.close()

@pgconnect
def getneuronfolder(conn,neuron_name):
    # get archive of ready neuron names
    cur = conn.cursor()

    statement = "SELECT foldername FROM ingested_archives,ingestion WHERE ingested_archives.name = ingestion.archive AND ingestion.neuron_name = '{}' order by ingested_archives.date desc limit 1".format(neuron_name.replace("'","''"))
    cur.execute(statement)
    result = cur.fetchone()
    res = result[0]
    return res

@pgconnect
def getfoldername(conn,neuron_name):
    # get archive of ready neuron names
    cur = conn.cursor()

    statement = "SELECT foldername FROM ingested_archives WHERE name = '{}'".format(neuron_name)
    cur.execute(statement)
    result = cur.fetchone()
    res = result[0]
    return res

@pgconnect
def getfolderfromname(conn,archive_name):
    # get archive of ready neuron names
    cur = conn.cursor()

    statement = "SELECT foldername FROM ingested_archives WHERE ingested_archives.name = '{}' ORDER BY ingested_archives.date desc limit 1".format(archive_name)
    cur.execute(statement)
    result = cur.fetchone()
    res = result[0]
    return res

@pgconnect
def getneuronarchive(conn,neuron_name):
    # get archive of ready neuron names
    cur = conn.cursor()

    statement = "SELECT archive FROM ingestion WHERE ingestion.neuron_name = '{}'".format(neuron_name.replace("'","''"))
    cur.execute(statement)
    result = cur.fetchone()
    if result is None:
        res = None
    else:
        res = result[0]
    conn.close()
    return res

@myconnect
def mygetneuronarchive(conn,neuron_name):
    # get archive of ready neuron names
    cur = conn.cursor()

    statement = "SELECT name FROM archive  WHERE archive.id.neuron_name = '{}'".format(neuron_name.replace("'","''"))
    cur.execute(statement)
    result = cur.fetchone()
    res = result[0]
    conn.close()
    return res

@myconnect
def my_getarchiveneurons(conn,archive):
    """
    get all neurons for archive from old db
    """
    cur = conn.cursor()
    stmt = "SELECT neuron_name from neuron,archive where neuron.archive_id = archive.archive_id AND archive_name = '{}'".format(archive)
    cur.execute(stmt)
    res = cur.fetchall()
    res = [item[0] for item in res]
    return res


@pgconnect
def getarchiveneurons(conn,archive,skip_public=False):
    cur = conn.cursor()
    status_clause = "AND COALESCE(ingestion.status,'') <> 'public'" if skip_public else ""
    statement = "SELECT neuron.name,neuron.id from neuron,ingestion where neuron.name = ingestion.neuron_name AND ingestion.archive = '{}' {}".format(archive,status_clause)
    cur.execute(statement)
    res = cur.fetchall()
    resultnames = [item[0] for item in res]
    resultids = [item[1] for item in res]
    return (resultnames,resultids)


def settarget(targetdb):
    cfg.dbsel = targetdb

@pgconnect
def getarchivemeasurements(conn,archive):
    cur = conn.cursor()
    statement = "SELECT neuron.summary_meas_id from neuron,ingestion where neuron.name = ingestion.neuron_name AND ingestion.archive = '{}'".format(archive)
    cur.execute(statement)
    res = cur.fetchall()
    resultids = [item[0] for item in res]
    return resultids

def setneuronerror(neuron_name,message):
    # get array of ready neuron names
    conn = connect()
    cur = conn.cursor()

    statement = "UPDATE ingestion SET status='error', message = '{}' WHERE neuron_name = '{}'".format(cleanerr(message),neuron_name.replace("'","''"))
    cur.execute(statement)
    conn.close()

@pgconnect
def pginsert(conn,tablename,data):
    """
    Generic function, inserts data values defined as key-value pairs into named table  
    """
    cur = conn.cursor()
    data = {item: data[item] for item in data if data[item] is not None}
    fields = ",".join(data.keys())
    values = "','".join([str(item).replace("'","''") for item in data.values()])
    statement = """INSERT INTO {}({}) VALUES ('{}') """.format(tablename,fields,values)
    cur.execute(statement)  
    cur.execute("select currval('{}_id_seq')".format(tablename))
    result = cur.fetchone()
    inserted_id = result[0]
    return inserted_id
