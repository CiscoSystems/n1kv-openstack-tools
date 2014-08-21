#!/usr/bin/python 
# cwchang v5
import sqlite3
import os
import sys
import string
import time
import logging
import logging.handlers
import subprocess

#
# constants
#
max_log_size = 10240 * 1000
working_dir = '/var/spool/'
sources = ['neutron', 'horizon', 'python-neutronclient']
#
# debug tool : help to generate test data 
archive_check_cmd = './simulated_rmadison'
#archive_check_cmd = 'rmadison'

attributes = [
    'source',
    'version',
    'version_security',
    'version_updates',
    'max_version',
    'max_dist',
    'updated_version',
]


#
# global variable 
#
log_file = ''
new_packages_needed = False
main_dist = ''
relevant_dists = {}

db_record = {
    'source' : '',
    'version' : '',
    'version_security' : '',
    'version_updates' : '',
    'max_version' : '',
    'max_dist' : '',
}

code_base_record = {}
input_record = {}
output_record = {}

if (len(sys.argv) != 2):
   exit('usage: {0} <precise|trusty|...distribution>\n'.format(sys.argv[0]))

main_dist = sys.argv[1]

log_file = '{0}n1kv-log-openstack_{1}.txt'.format(working_dir, main_dist)
db_file = '{0}n1kv-version-openstack-{1}.db'.format(working_dir, main_dist)
code_base_file = '{0}n1kv-code-base-openstack-{1}.txt'.format(working_dir, main_dist)


def generate_output(source, max_dist, max_version, version, init_time):

    base1 = code_base_record[source][0]
    base2 = max_version.split('-')[0].split(':')[1]

    if base1 > base2:
        output = '{0}:-1 -1 -1 -1'.format(source)
        return_value = False
        return (output, return_value)
    
    if max_version > version:
        output = '{0}:{1} {2} {3} {4}'.format(source,
                                          max_dist,
                                          max_version,
                                          code_base_record[source][1],
                                          code_base_record[source][2])
        return_value  = True
    else:
        if max_version == version:
           if init_time == True:
               output = '{0}:{1} {2} {3} {4}'.format(source,
                                                     max_dist,
                                                     max_version,
                                                     code_base_record[source][1],
                                                     code_base_record[source][2])
           else: 
               output = '{0}:-1 -1 -1 -1'.format(source)
        else:
            output = '{0}:-1 -1 -1 -1'.format(source)

        return_value = False

    return (output, return_value)
    
######################################################################

logging.basicConfig(filename=log_file,level=logging.DEBUG)

logger = logging.getLogger('n1kv_logger')
logger.setLevel(logging.DEBUG)

handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=max_log_size, backupCount=5)

logger.addHandler(handler)

#
# Read in code base file 
# key    0                 1          2
# source openstack-version git-branch git-tag
#
for source in sources:
    code_base_record[source] = ['-1', '', '']

if os.path.isfile(code_base_file) == True:    
    with open(code_base_file, 'r') as f:
        for line in f:
            #
            # skip comment line
            #
            if line[0] == '#':
                continue

            line1 = line.replace('\n', '')

            if line1 == '':
                continue

            record = line1.split(' ')
            source = record[0]
            code_base_record[source] = record[1:]
            #print(code_base_record[source])
else:
   exit('need code base file {0}'.format(code_base_file))

#
# compose distribution based on input 'dist'
#
for source in sources: 
    #
    # initialize input_record
    #
    input_record[source] = {}

    input_record[source][main_dist] = '-1'
    input_record[source]['max_dist'] = ''
    input_record[source]['max_version'] = '-1'

    relevant_dists[main_dist] = True

    for d in ['security', 'updates']:
        dist = '{0}-{1}'.format(main_dist, d)
        #
        # create emptry entry container for each dist
        #
        input_record[source][dist] = '-1' 
        relevant_dists[dist] = True


    logger.debug('{0}: checking {1}'.format(time.strftime('%m/%d/%Y-%H:%M:%S'),
                                            source))

    cmd = '{0} {1} | grep {2}'.format(archive_check_cmd, source, main_dist)           
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=None, shell=True)

    return_list = p.communicate()

    #
    # source does not exist
    #
    if len(return_list) <= 0:
        continue
    
    return_list1 = return_list[0].split('\n')

    max_version = '-1'
    max_dist = main_dist

    for row in return_list1:
        list = row.split('|')

        if len(list) < 3:
            continue

        source = list[0].replace(' ', '')
        version = list[1].replace(' ', '')
        dist = list[2].replace(' ', '')

        logger.debug('{0}: {1} {2} {3}'.format(time.strftime('%m/%d/%Y-%H:%M:%S'),
                                               source,
                                               version,
                                               dist))

        
        try:
            if relevant_dists[dist] == True:
                pass
        except:

            logger.debug('{0}: skip {1} {2}'.format(time.strftime('%m/%d/%Y-%H:%M:%S'),
                                               source,
                                               dist))
            continue

        #
        # current patchable code base
        #
        base1 = code_base_record[source][0]
        base2 = version.split('-')[0].split(':')[1]
       
        input_record[source][dist] = version

        if version > max_version and base1 >= base2:
            max_version = version
            max_dist = dist

    #
    # keep track of max version and max dist
    #
    input_record[source]['max_version'] = max_version
    input_record[source]['max_dist'] = max_dist

#
# Debugging 
#
for source in sources:
    logger.debug('{0}: {1} max_version: {2} {3}'.format(time.strftime('%m/%d/%Y-%H:%M:%S'),
                                                        source, 
                                                        input_record[source]['max_version'],
                                                        input_record[source]['max_dist']))
    #print('{0}: {1} max_version: {2} {3}'.format(time.strftime('%m/%d/%Y-%H:%M:%S'),
                                                        #source, 
                                                        #input_record[source]['max_version'],
                                                        #input_record[source]['max_dist']))


#
# See if a database state already there, if not create one
# 
if os.path.isfile(db_file) == False: 

    #
    # Create database model
    #
    cmd = 'CREATE TABLE Packages(id INTEGER PRIMARY KEY'
    
    for a in attributes:
        cmd = cmd + ', ' + a + ' TEXT'

    cmd = cmd + ')'
    db = sqlite3.connect(db_file)
    cursor = db.cursor()
    cursor.execute(cmd)

    #
    # fill up database
    #
    for source in sources:
        output_record[source] = ''

        db_record['source'] = source

        for key in input_record[source].keys():
            if key.find('security') >= 0:
                db_record['version_security'] = input_record[source][key]
            elif key.find('updates') >= 0:
                db_record['version_updates'] = input_record[source][key]
            elif key.find(main_dist) >= 0:
                db_record['version'] = input_record[source][key]

        db_record['max_version'] = input_record[source]['max_version']
        db_record['max_dist'] = input_record[source]['max_dist']

        (output_record[source], new_packages_needed1) =  \
                  generate_output(source, 
                                  input_record[source]['max_dist'],
                                  input_record[source]['max_version'],
                                  db_record['version'],
                                  True)
        if new_packages_needed1 == True:
            new_packages_needed = True 
                                                
        sql_cmd1 = 'INSERT INTO Packages('
        sql_cmd2 = 'VALUES('
        sql_cmd3 = ()

        for a in attributes:
            if a == 'source':
                sql_cmd1 = sql_cmd1 + a
                sql_cmd2 = sql_cmd2 + '?'
            else:
                sql_cmd1 = sql_cmd1 + ',' + a
                sql_cmd2 = sql_cmd2 + ',?'

            if a == 'max_version':
                db_record['updated_version'] = db_record[a]

            sql_cmd3 += (db_record[a],)

        sql_cmd1 = sql_cmd1 + ') ' 
        sql_cmd2 = sql_cmd2 + ')'

        cmd = sql_cmd1 + ' ' + sql_cmd2

        cursor.execute(cmd, sql_cmd3) 
    #
    # end of each source 
    #

    db.commit()
#
# we have a previous version database to check...
# 
else: 
    db = sqlite3.connect(db_file)
    cursor = db.cursor()

    for source in sources:
        output_record[source] = ''

        cursor.execute(''' SELECT * FROM Packages WHERE source = ?''', (source,))
        row = cursor.fetchone()

        #print row[0], row[1]

        logger.debug('{0}: max_dist{1} max_version{2} db.updated_version{3}'.format(
                                           time.strftime('%m/%d/%Y-%H:%M:%S'),
                                           input_record[source]['max_dist'],
                                           input_record[source]['max_version'],
                                           row[7]))

        (output_record[source], new_packages_needed1) = \
                       generate_output(source, 
                                       input_record[source]['max_dist'],
                                       input_record[source]['max_version'],
                                       row[7], 
                                       False)

        if new_packages_needed1 == True:
            cursor.execute(''' UPDATE Packages SET max_dist = ?, max_version = ?, updated_version = ? WHERE id = ?''', 
                           (input_record[source]['max_dist'], 
                            input_record[source]['max_version'], 
                            input_record[source]['max_version'], 
                            row[0]))
            db.commit()
            new_packages_needed = True
    
if new_packages_needed == True:
    cmd = 'ssh cwchang@10.28.29.132 /users/cwchang/bin/trigger-mail ' + '\\"' 
    for source in sources:
        if output_record[source] != '':
            cmd += '{0} '.format(output_record[source])

    cmd += '\\"'

    #os.system(cmd)
    #print cmd


for source in sources:
    if output_record[source] != '':
        print(output_record[source])

