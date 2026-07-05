import os 

data_root = os.getenv('ARE_DATA_ROOT', '/home/kira/app/Ingestion/data')

remotepath = os.getenv('ARE_REMOTEPATH', os.path.join(data_root, 'NMOV8.0-ongoing') + '/')
#remotepath = '/home/datashare/NMOVersionReleases/NMOV8.7-ongoing/ongoing/onging/'
readyremotepath = os.getenv('ARE_READY_REMOTEPATH', data_root)
#remotepath = '/run/user/1000/gvfs/smb-share:server=cngfile.orc.gmu.edu,share=nmofile/ToBackup/NMOVersionReleases/NMOV8.6-ongoing/'

#datapath = '/mnt/cngfile/ToBackup/NMOVersionReleases/NMOV8.0-ongoing/'
remotemetapath = os.getenv('ARE_REMOTE_METAPATH', os.path.join(data_root, 'NMOV8.7-metadata') + '/')
#remotemetapath = '/home/datashare/NMOVersionReleases/NMOV8.7-metadata/meta/metadata/'

#metapath = '/mnt/cngfile/ToBackup/NMOVersionReleases/NMOV8.0-metadata/'
datapath = os.getenv('ARE_DATAPATH', os.path.join(data_root, 'archives') + '/')
metapath = os.getenv('ARE_METAPATH', os.path.join(data_root, 'metadata') + '/')
scrollpath = os.getenv('ARE_SCROLLPATH', os.path.join(data_root, 'scrollimages') + '/')

# Definition file /home/bljungqu/are/readyarchives.csv
readyarchives = os.path.join(readyremotepath,'readyarchives.csv')
#readyarchives = os.path.join('/home/bljungqu/are','readyarchives.csv')

# MySQL config
dbhost = os.getenv('ARE_MYSQL_HOST', 'localhost')
dbuser = os.getenv('ARE_MYSQL_USER', 'blxps')
dbpass = os.getenv('ARE_MYSQL_PASSWORD', '100%db')
dbselrev = os.getenv('ARE_MYSQL_REVIEW_DB', 'nmdbDev')
dbsel = os.getenv('ARE_MYSQL_DB', dbselrev)
dbselmain = os.getenv('ARE_MYSQL_MAIN_DB', 'NeuMO')
db_auth_plugin = os.getenv('ARE_MYSQL_AUTH_PLUGIN', 'mysql_native_password')

# PostgreSQL config used by the ingestion/release state tables.
pg_host = os.getenv('ARE_POSTGRES_HOST', 'localhost')
pg_port = int(os.getenv('ARE_POSTGRES_PORT', '5432'))
pg_database = os.getenv('ARE_POSTGRES_DB', 'nmo')
pg_user = os.getenv('ARE_POSTGRES_USER', 'nmo')
pg_password = os.getenv('ARE_POSTGRES_PASSWORD', '100neuralDB')

#SSH config
#sshuser = 'root',
#sshkeyfile = '/.ssh/id_rsa'
sshuser = 'bljungqu',
sshkeyfile = '/home/bljungqu/.ssh/id_rsa'
sshhost = 'cng.gmu.edu'
review_webapp_root = os.getenv(
    'ARE_SSH_REVIEW_DIR',
    os.path.join(data_root, 'apache-tomcat-9.0.118', 'webapps', 'neuroMorphoReview')
)
main_webapp_root = os.getenv(
    'ARE_SSH_MAIN_DIR',
    os.path.join(data_root, 'apache-tomcat-9.0.118', 'webapps', 'neuroMorpho')
)
sshdir = review_webapp_root.rstrip('/') + '/'
sshmaindir = main_webapp_root.rstrip('/') + '/'
sshreviewdir = review_webapp_root.rstrip('/') + '/'


# Duplicate detection
#duplicateurl = 'http://129.174.10.74/simDev/getDuplicates/'
#duplicateinternalurl = 'http://129.174.10.74/simDev/getDuplicates/'
duplicateinternalurl = os.getenv('ARE_DUPLICATE_URL', 'http://similarity-search:5000/getDuplicatesfordata/')
similaritylim = 0.999999
pcalim = 0.9999

# Web server to check files
webserver = 'http://localhost:8080//neuroMorphoReview/'

#URL to pvec generation
#pvecurl = 'https://neuromorpho.org/swc2pvec/'
#pvecurl = 'http://100.28.253.215/swc2pvec/'
pvecurl = os.getenv('ARE_PVEC_URL', 'http://swc2pvec:5000/')

#Twitter keys

twitterparams = {
    'consumer_key': "y6vLTNiRFwNpcUd4Rk6ntVDo3",
    'consumer_secret': "FdSETIgoxXIGkcJseOvgIGQcyZtUr7eFqzdoUB8I9WciJSWFaB",
    'access_token_key': "223121018-2YOxlA3Babx1pqbhtyOHsEYA7l1siy6VenVr46w6",
    'access_token_secret': "wfrCDCrkZfu87VbpWH4rcx2OwSi4YhW37ug2oHzisOQ2L"
}
"""
twitterparams = {
    'consumer_key': "Vvmx2Qk6W55LO7oqQzfJvolOt",
    'consumer_secret': "cSlnRgvb7x1u2ELtnrj7dYeHeHQGXcAdThqM3geEZP25BczSUj",
    'access_token_key': "223121018-HxATKDLVdWG11PqUk3ejuMSC8AtSLh4dcqkODVrw",
    'access_token_secret': "3X1vdcIutFqTDCx8KcN6iGoaitF4kAtpyO6FS7Ayu91Tt"
}
"""

"""
twitterparams = {
    'consumer_key': "GxV2DJEMgTroFYrprIwSvzuWd",
    'consumer_secret': "99HJcHECIpFvX6S8ISZG60pjraf3hknpzZCPM10iTzGpfgz0Pz",
    'access_token_key': "223121018-07PMUwHOfArzFp7R9HTZWk9Rxh4B89yyqQE3xnDw",
    'access_token_secret': "Ge2Zc34FtePAaJuQCeSUKQVljBglDfy20pulRVhfrgzoH"
}"""

"""
twitterparams = {
    'consumer_key': "C40UsLnaIpmICqVdHRTRz9REb",
    'consumer_secret': "A49sh5mWu9pOYdb6aX1jNXp5hGrI43HMxBvU1cUf67MlTf0e1o",
    'access_token_key': "1323725062738857986-OxWAc0Qz7M5Q2DH1YFPd79ehRShKtu",
    'access_token_secret': "eMrIN3RnV5V5Q52NaXg4x3wNVjFRpi0UM7KqDoNGE1leQ"
}
"""
#bearer
#AAAAAAAAAAAAAAAAAAAAADaJJgEAAAAA6O6ACk2rZx2sLfsChEtdYqG0TAM%3DGsStzKLgpjzz82srsHJpF9sUplCExNPt2IEbvUUBPcD4ZXbFEU
