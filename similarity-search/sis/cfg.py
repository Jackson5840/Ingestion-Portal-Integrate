import os

basemetadir = os.getenv('SIS_BASE_META_DIR', '')
basereleasedir = os.getenv('SIS_BASE_RELEASE_DIR', '')
pathonserver = os.getenv('SIS_PATH_ON_SERVER', '')

# Define nonsense data and mismatch dataframe
nondata = {'.DS_Store','._.DS_Store','desktop.ini'}
html_head = '''
<html>
  <head><title>Test report</title>
  <script src="js/sorttable.js"></script>
  <link rel="stylesheet" type="text/css" href="css/df_style.css"/>

  
  </head>
  <body>
'''
html_footer = '''
  </body>
</html>.
'''

keyfile_path= os.getenv('SIS_KEYFILE_PATH', '')

host = os.getenv('SIS_SSH_HOST', '')
port = int(os.getenv('SIS_SSH_PORT', '22'))
username = os.getenv('SIS_SSH_USER', '')


dbhost = os.getenv('SIS_MYSQL_HOST', '')
dbuser = os.getenv('SIS_MYSQL_USER', '')
dbpass = os.getenv('SIS_MYSQL_PASSWORD', '')
dbsel = os.getenv('SIS_MYSQL_DB', '')
dbtimeout = int(os.getenv('SIS_MYSQL_TIMEOUT', '500000'))
db_auth_plugin = os.getenv('SIS_MYSQL_AUTH_PLUGIN', 'mysql_native_password')
