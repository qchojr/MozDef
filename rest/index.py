# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# Copyright (c) 2014 Mozilla Corporation

import bottle
import json
import netaddr
import os
import pynsive
import random
import re
import requests
import socket
import importlib
from bottle import route, run, response, request, default_app, post
from datetime import datetime, timedelta
from configlib import getConfig, OptionParser
from ipwhois import IPWhois
from operator import itemgetter
from pymongo import MongoClient
from bson import json_util, ObjectId
from bson.codec_options import CodecOptions

from mozdef_util.elasticsearch_client import ElasticsearchClient, ElasticsearchInvalidIndex
from mozdef_util.query_models import SearchQuery, TermMatch

from mozdef_util.utilities.logger import logger, initLogger
from mozdef_util.utilities.toUTC import toUTC


options = None
pluginList = list()   # tuple of module,registration dict,priority


def enable_cors(fn):
    ''' cors decorator for rest/ajax'''
    def _enable_cors(*args, **kwargs):
        # set CORS headers
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'

        if bottle.request.method != 'OPTIONS':
            # actual request; reply with the actual response
            return fn(*args, **kwargs)

    return _enable_cors


@route('/test')
@route('/test/')
def test():
    '''test endpoint for..testing'''
    # ip = request.environ.get('REMOTE_ADDR')
    # response.headers['X-IP'] = '{0}'.format(ip)
    response.status = 200

    sendMessgeToPlugins(request, response, 'test')
    return response


@route('/status')
@route('/status/')
def status():
    '''endpoint for a status/health check'''
    if request.body:
        request.body.read()
        request.body.close()
    response.status = 200
    response.content_type = "application/json"
    response.body = json.dumps(dict(status='ok', service='restapi'))
    sendMessgeToPlugins(request, response, 'status')
    return response


@route('/getwatchlist')
@route('/getwatchlist/')
def status():
    '''endpoint for grabbing watchlist contents'''
    if request.body:
        request.body.read()
        request.body.close()
    response.status = 200
    response.content_type = "application/json"
    response.body = getWatchlist()
    return response


@route('/logincounts')
@route('/logincounts/')
@enable_cors
def index():
    '''an endpoint to return success/failed login counts'''
    if request.body:
        request.body.read()
        request.body.close()
    response.content_type = "application/json"
    sendMessgeToPlugins(request, response, 'logincounts')
    return response


@route('/veris')
@route('/veris/')
@enable_cors
def index():
    '''returns a count of veris tags'''
    if request.body:
        request.body.read()
        request.body.close()
    response.content_type = "application/json"
    response.body = verisSummary()
    sendMessgeToPlugins(request, response, 'veris')
    return response


@route('/kibanadashboards')
@route('/kibanadashboards/')
@enable_cors
def index():
    '''returns a list of dashboards to show on the UI'''
    if request.body:
        request.body.read()
        request.body.close()

    response.content_type = "application/json"
    response.body = kibanaDashboards()
    sendMessgeToPlugins(request, response, 'kibanadashboards')
    return response


@post('/blockip', methods=['POST'])
@post('/blockip/', methods=['POST'])
@enable_cors
def index():
    '''will receive a call to block an ip address'''
    sendMessgeToPlugins(request, response, 'blockip')
    return response


@post('/blockfqdn', methods=['POST'])
@post('/blockfqdn/', methods=['POST'])
@enable_cors
def index():
    '''will receive a call to block an ip address'''
    sendMessgeToPlugins(request, response, 'blockfqdn')
    return response


@post('/watchitem', methods=['POST'])
@post('/watchitem/', methods=['POST'])
@enable_cors
def index():
    '''will receive a call to watchlist a specific term'''
    sendMessgeToPlugins(request, response, 'watchitem')
    return response


@post('/ipwhois', methods=['POST'])
@post('/ipwhois/', methods=['POST'])
@enable_cors
def index():
    '''return a json version of whois for an ip address'''
    if request.body:
        arequest = request.body.read()
        request.body.close()
    # valid json?
    try:
        requestDict = json.loads(arequest)
    except ValueError:
        response.status = 500

    if 'ipaddress' in requestDict and isIPv4(requestDict['ipaddress']):
        response.content_type = "application/json"
        response.body = getWhois(requestDict['ipaddress'])
    else:
        response.status = 500

    sendMessgeToPlugins(request, response, 'ipwhois')
    return response


@post('/ipintel', methods=['POST'])
@post('/ipintel/', methods=['POST'])
@enable_cors
def ipintel():
    '''send an IP address through plugins for intel enhancement'''
    if request.body:
        arequest = request.body.read()
        # request.body.close()
    # valid json?
    try:
        requestDict = json.loads(arequest)
    except ValueError:
        response.status = 500
    if 'ipaddress' in requestDict and isIPv4(requestDict['ipaddress']):
        response.content_type = "application/json"
    else:
        response.status = 500

    sendMessgeToPlugins(request, response, 'ipintel')
    return response


@post('/ipdshieldquery', methods=['POST'])
@post('/ipdshieldquery/', methods=['POST'])
@enable_cors
def index():
    '''
    return a json version of dshield query for an ip address
    https://isc.sans.edu/api/index.html
    '''
    if request.body:
        arequest = request.body.read()
        request.body.close()
    # valid json?
    try:
        requestDict = json.loads(arequest)
    except ValueError:
        response.status = 500
        return
    if 'ipaddress' in requestDict and isIPv4(requestDict['ipaddress']):
        url="https://isc.sans.edu/api/ip/"

        headers = {
            'User-Agent': options.user_agent
        }

        dresponse = requests.get('{0}{1}?json'.format(url, requestDict['ipaddress']), headers=headers)
        if dresponse.status_code == 200:
            response.content_type = "application/json"
            response.body = dresponse.content
        else:
            response.status = dresponse.status_code

    else:
        response.status = 500

    sendMessgeToPlugins(request, response, 'ipdshieldquery')
    return response


@route('/alertschedules')
@route('/alertschedules/')
@enable_cors
def index():
    '''an endpoint to return alert schedules'''
    if request.body:
        request.body.read()
        request.body.close()
    response.content_type = "application/json"
    mongoclient = MongoClient(options.mongohost, options.mongoport)
    schedulers_db = mongoclient.meteor['alertschedules'].with_options(codec_options=CodecOptions(tz_aware=True))

    mongodb_alerts = schedulers_db.find()
    alert_schedules_dict = {}
    for mongodb_alert in mongodb_alerts:
        if mongodb_alert['last_run_at']:
            mongodb_alert['last_run_at'] = mongodb_alert['last_run_at'].isoformat()
        if 'modifiedat' in mongodb_alert:
            mongodb_alert['modifiedat'] = mongodb_alert['modifiedat'].isoformat()
        alert_schedules_dict[mongodb_alert['name']] = mongodb_alert

    response.body = json.dumps(alert_schedules_dict)
    response.status = 200
    return response


@post('/syncalertschedules', methods=['POST'])
@post('/syncalertschedules/', methods=['POST'])
@enable_cors
def sync_alert_schedules():
    '''an endpoint to return alerts schedules'''
    if not request.body:
        response.status = 503
        return response

    alert_schedules = json.loads(request.body.read())
    request.body.close()

    response.content_type = "application/json"
    mongoclient = MongoClient(options.mongohost, options.mongoport)
    schedulers_db = mongoclient.meteor['alertschedules'].with_options(codec_options=CodecOptions(tz_aware=True))
    results = schedulers_db.find()
    for result in results:
        if result['name'] in alert_schedules:
            new_sched = alert_schedules[result['name']]
            result['total_run_count'] = new_sched['total_run_count']
            result['last_run_at'] = new_sched['last_run_at']
            if result['last_run_at']:
                result['last_run_at'] = toUTC(result['last_run_at'])
            logger.debug("Inserting schedule for {0} into mongodb".format(result['name']))
            schedulers_db.save(result)

    response.status = 200
    return response


@post('/updatealertschedules', methods=['POST'])
@post('/updatealertschedules/', methods=['POST'])
@enable_cors
def update_alert_schedules():
    '''an endpoint to return alerts schedules'''
    if not request.body:
        response.status = 503
        return response

    alert_schedules = json.loads(request.body.read())
    request.body.close()

    response.content_type = "application/json"
    mongoclient = MongoClient(options.mongohost, options.mongoport)
    schedulers_db = mongoclient.meteor['alertschedules'].with_options(codec_options=CodecOptions(tz_aware=True))
    schedulers_db.remove()

    for alert_name, alert_schedule in alert_schedules.items():
        if alert_schedule['last_run_at']:
            alert_schedule['last_run_at'] = toUTC(alert_schedule['last_run_at'])
        logger.debug("Inserting schedule for {0} into mongodb".format(alert_name))
        schedulers_db.insert(alert_schedule)

    response.status = 200
    return response


@route('/plugins', methods=['GET'])
@route('/plugins/', methods=['GET'])
@route('/plugins/<endpoint>', methods=['GET'])
def getPluginList(endpoint=None):
    ''' return a json representation of the plugin tuple
        (mname, mclass, mreg, mpriority)
         minus the actual class (which isn't json-able)
         for all plugins, or for a specific endpoint
    '''
    pluginResponse = list()
    if endpoint is None:
        for plugin in pluginList:
            pdict = {}
            pdict['file'] = plugin[0]
            pdict['name'] = plugin[1]
            pdict['description'] = plugin[2]
            pdict['registration'] = plugin[3]
            pdict['priority'] = plugin[4]
            pluginResponse.append(pdict)
    else:
        # filter the list to just the endpoint requested
        for plugin in pluginList:
            if endpoint in plugin[3]:
                pdict = {}
                pdict['file'] = plugin[0]
                pdict['name'] = plugin[1]
                pdict['description'] = plugin[2]
                pdict['registration'] = plugin[3]
                pdict['priority'] = plugin[4]
                pluginResponse.append(pdict)
    response.content_type = "application/json"
    response.body = json.dumps(pluginResponse)

    sendMessgeToPlugins(request, response, 'plugins')
    return response


@post('/incident', methods=['POST'])
@post('/incident/', methods=['POST'])
def createIncident():
    '''
    endpoint to create an incident

    request body eg.
    {
        "summary": <string>,
        "phase": <enum: case-insensitive>
                        Choose from ('Identification', 'Containment', 'Eradication',
                                     'Recovery', 'Lessons Learned', 'Closed')
        "creator": <email>,

        // Optional Arguments

        "description": <string>,
        "dateOpened": <string: yyyy-mm-dd hh:mm am/pm>,
        "dateClosed": <string: yyyy-mm-dd hh:mm am/pm>,
        "dateReported": <string: yyyy-mm-dd hh:mm am/pm>,
        "dateVerified": <string: yyyy-mm-dd hh:mm am/pm>,
        "dateMitigated": <string: yyyy-mm-dd hh:mm am/pm>,
        "dateContained": <string: yyyy-mm-dd hh:mm am/pm>,
        "tags": <list <string>>,
        "references": <list <string>>
    }
    '''

    client = MongoClient(options.mongohost, options.mongoport)
    incidentsMongo = client.meteor['incidents']

    response.content_type = "application/json"
    EMAIL_REGEX = r"^[A-Za-z0-9\.\+_-]+@[A-Za-z0-9\._-]+\.[a-zA-Z]*$"

    if not request.body:
        response.status = 500
        response.body = json.dumps(dict(status='failed',
                                        error='No data provided'))

        return response

    try:
        body = json.loads(request.body.read())
        request.body.close()
    except ValueError:
        response.status = 500
        response.body = json.dumps(dict(status='failed',
                                        error='Invalid JSON'))

        return response

    incident = dict()

    validIncidentPhases = ('Identification', 'Containment', 'Eradication',
                           'Recovery', 'Lessons Learned', 'Closed')

    incident['_id'] = generateMeteorID()
    try:
        incident['summary'] = body['summary']
        incident['phase'] = body['phase']
        incident['creator'] = body['creator']
        incident['creatorVerified'] = False
    except KeyError:
        response.status = 500
        response.body = json.dumps(dict(status='failed',
                                        error='Missing required keys'
                                              '(summary, phase, creator)'))
        return response

    # Validating Incident phase type
    if (type(incident['phase']) is not str or
            incident['phase'] not in validIncidentPhases):

        response.status = 500
        response.body = json.dumps(dict(status='failed',
                                        error='Invalid incident phase'))
        return response

    # Validating creator email
    if not re.match(EMAIL_REGEX, incident['creator']):
        response.status = 500
        response.body = json.dumps(dict(status='failed',
                                        error='Invalid creator email'))
        return response

    incident['description'] = body.get('description')
    incident['dateOpened'] = validateDate(body.get('dateOpened', datetime.now()))
    incident['dateClosed'] = validateDate(body.get('dateClosed'))
    incident['dateReported'] = validateDate(body.get('dateReported'))
    incident['dateVerified'] = validateDate(body.get('dateVerified'))
    incident['dateMitigated'] = validateDate(body.get('dateMitigated'))
    incident['dateContained'] = validateDate(body.get('dateContained'))

    dates = [
        incident['dateOpened'],
        incident['dateClosed'],
        incident['dateReported'],
        incident['dateVerified'],
        incident['dateMitigated'],
        incident['dateContained']
    ]

    # Validating all the dates for the format
    if False in dates:
        response.status = 500
        response.body = json.dumps(dict(status='failed',
                                        error='Wrong format of date. Please '
                                              'use yyyy-mm-dd hh:mm am/pm'))
        return response

    incident['tags'] = body.get('tags')

    if incident['tags'] and type(incident['tags']) is not list:
        response.status = 500
        response.body = json.dumps(dict(status='failed',
                                        error='tags field must be a list'))
        return response

    incident['references'] = body.get('references')

    if incident['references'] and type(incident['references']) is not list:
        response.status = 500
        response.body = json.dumps(dict(status='failed',
                                        error='references field must be a list'))
        return response

    # Inserting incident dict into mongodb
    try:
        incidentsMongo.insert(incident)
    except Exception as err:
        response.status = 500
        response.body = json.dumps(dict(status='failed',
                                        error=err))
        return response

    response.status = 200
    response.body = json.dumps(dict(status='success',
                                    message='Incident: <{}> added.'.format(
                                        incident['summary'])
                                    ))
    return response


@post('/alertstatus')
@post('/alertstatus/')
def update_alert_status():
    '''Update the status of an alert.

    Requests are expected to take the following (JSON) form:

    ```
    {
        "alert": str,
        "status": str,
        "user": {
            "email": str,
            "slack": str
        },
        "identityConfidence": str
        "response": str
    }
    ```

    Where:
        * `"alert"` is the unique identifier fo the alert whose status
        we are to update.
        * `"status"` is one of "manual", "inProgress", "acknowledged"
        or "escalated".
        * `confidence` is one of "highest", "high", "moderate", "low",
        or "lowest".


    This function writes back a response containing the following JSON.

    ```
    {
        "error": Optional[str]
    }
    ```

    If an error occurs and the alert is not able to be updated, then
    the "error" field will contain a string message describing the issue.
    Otherwise, this field will simply be `null`.  This function will,
    along with updating the alert's status, append information about the
    user and their response to `alert['details']['triage']`.

    Responses will also use status codes to indicate success / failure / error.
    '''

    ok = 200
    bad_request = 400

    mongo = MongoClient(options.mongohost, options.mongoport)
    alerts = mongo.meteor['alerts']

    response.content_type = 'appliation/json'

    try:
        req = json.loads(request.body.read())
        request.body.close()
    except ValueError:
        response.status = bad_request
        response.body = json.dumps({
            'error': 'Missing or invalid request body'
        })
        return response

    valid_statuses = ['manual', 'inProgress', 'acknowledged', 'escalated']

    if req['status'] not in valid_statuses: 
        response.status = bad_request
        response.body = json.dumps({
            'error': 'Status not one of {}'.format(' or '.join(valid_statuses))
        })
        return response

    valid_confidences = ['highest', 'high', 'moderate', 'low', 'lowest']

    if req['user']['confidence'] not in valid_confidences:
        response.status = bad_request
        response.body = json.dumps({
            'error': 'user.confidence not one of {}'.format(
                ' or '.join(valid_confidences))
        })
        return response

    triage = {
        'user': req['user'],
        'response': req['response']
    }

    modified_count = 0

    modified_count += alerts.update_one(
        {'esmetadata': {'id': req['alert']}},
        {'$set': {'status': req['status']}}
    ).modified_count

    modified_count += alerts.update_one(
        {'esmetadata': {'id': req['alert']}},
        {'$set': {'details': {'triage': triage}}}
    ).modified_count

    if modified_count < 2:
        response.status = bad_request
        response.body = json.dumps({
            'error': 'Alert not found'
        })
        return response

    response.status = ok
    response.body = json.dumps({'error': None})

    return response


def validateDate(date, dateFormat='%Y-%m-%d %I:%M %p'):
    '''
    Converts a date string into a datetime object based
    on the dateFormat keyworded arg.
    Default dateFormat: %Y-%m-%d %I:%M %p (example: 2015-10-21 2:30 pm)
    '''

    dateObj = None

    if type(date) == datetime:
        return date

    try:
        dateObj = datetime.strptime(date, dateFormat)
    except ValueError:
        dateObj = False
    except TypeError:
        dateObj = None
    finally:
        return dateObj


def generateMeteorID():
    return('%024x' % random.randrange(16**24))


def registerPlugins():
    '''walk the plugins directory
       and register modules in pluginList
       as a tuple: (mfile, mname, mdescription, mreg, mpriority, mclass)
    '''

    plugin_location = os.path.join(os.path.dirname(__file__), "plugins")
    module_name = os.path.basename(plugin_location)
    root_plugin_directory = os.path.join(plugin_location, '..')

    plugin_manager = pynsive.PluginManager()
    plugin_manager.plug_into(root_plugin_directory)

    if os.path.exists(plugin_location):
        modules = pynsive.list_modules(module_name)
        for mfile in modules:
            module = pynsive.import_module(mfile)
            importlib.reload(module)
            if not module:
                raise ImportError('Unable to load module {}'.format(mfile))
            else:
                if 'message' in dir(module):
                    mclass = module.message()
                    mreg = mclass.registration
                    mclass.restoptions = options.__dict__

                    if 'priority' in dir(mclass):
                        mpriority = mclass.priority
                    else:
                        mpriority = 100
                    if 'name' in dir(mclass):
                        mname = mclass.name
                    else:
                        mname = mfile

                    if 'description' in dir(mclass):
                        mdescription = mclass.description
                    else:
                        mdescription = mfile

                    if isinstance(mreg, list):
                        logger.info('[*] plugin {0} registered to receive messages from /{1}'.format(mfile, mreg))
                        pluginList.append((mfile, mname, mdescription, mreg, mpriority, mclass))


def sendMessgeToPlugins(request, response, endpoint):
    '''
       iterate the registered plugins
       sending the response/request to any that have
       registered for this rest endpoint
    '''
    # sort by priority
    for plugin in sorted(pluginList, key=itemgetter(4), reverse=False):
        if endpoint in plugin[3]:
            (request, response) = plugin[5].onMessage(request, response)


def isIPv4(ip):
    try:
        # netaddr on it's own considers 1 and 0 to be valid_ipv4
        # so a little sanity check prior to netaddr.
        # Use IPNetwork instead of valid_ipv4 to allow CIDR
        if '.' in ip and len(ip.split('.')) == 4:
            # some ips are quoted
            netaddr.IPNetwork(ip.strip("'").strip('"'))
            return True
        else:
            return False
    except:
        return False


def kibanaDashboards():
    resultsList = []
    try:
        es_client = ElasticsearchClient((list('{0}'.format(s) for s in options.esservers)))
        search_query = SearchQuery()
        search_query.add_must(TermMatch('type', 'dashboard'))
        results = search_query.execute(es_client, indices=['.kibana'])

        for dashboard in results['hits']:
            dashboard_id = dashboard['_id']
            if dashboard_id.startswith('dashboard:'):
                dashboard_id = dashboard_id.replace('dashboard:', '')

            resultsList.append({
                'name': dashboard['_source']['dashboard']['title'],
                'id': dashboard_id
            })

    except ElasticsearchInvalidIndex as e:
        logger.error('Kibana dashboard index not found: {0}\n'.format(e))

    except Exception as e:
        logger.error('Kibana dashboard received error: {0}\n'.format(e))

    return json.dumps(resultsList)


def getWatchlist():
    WatchList = []
    try:
        # connect to mongo
        client = MongoClient(options.mongohost, options.mongoport)
        mozdefdb = client.meteor
        watchlistentries = mozdefdb['watchlist']

        # Log the entries we are removing to maintain an audit log
        expired = watchlistentries.find({'dateExpiring': {"$lte": datetime.utcnow() - timedelta(hours=1)}})
        for entry in expired:
            logger.debug('Deleting entry {0} from watchlist /n'.format(entry))

        # delete any that expired
        watchlistentries.delete_many({'dateExpiring': {"$lte": datetime.utcnow() - timedelta(hours=1)}})

        # Lastly, export the combined watchlist
        watchCursor=mozdefdb['watchlist'].aggregate([
            {"$sort": {"dateAdded": -1}},
            {"$match": {"watchcontent": {"$exists": True}}},
            {"$match":
                {"$or":[
                    {"dateExpiring": {"$gte": datetime.utcnow()}},
                    {"dateExpiring": {"$exists": False}},
                ]},
             },
            {"$project":{"watchcontent":1}},
        ])
        for content in watchCursor:
            WatchList.append(
                content['watchcontent']
            )
        return json.dumps(WatchList)
    except ValueError as e:
        logger.error('Exception {0} collecting watch list\n'.format(e))


def getWhois(ipaddress):
    try:
        whois = dict()
        ip = netaddr.IPNetwork(ipaddress)[0]
        if (not ip.is_loopback() and not ip.is_private() and not ip.is_reserved()):
            whois = IPWhois(netaddr.IPNetwork(ipaddress)[0]).lookup_whois()

        whois['fqdn']=socket.getfqdn(str(netaddr.IPNetwork(ipaddress)[0]))
        return (json.dumps(whois))
    except Exception as e:
        logger.error('Error looking up whois for {0}: {1}\n'.format(ipaddress, e))


def verisSummary(verisRegex=None):
    try:
        # aggregate the veris tags from the incidents collection and return as json
        client = MongoClient(options.mongohost, options.mongoport)
        # use meteor db
        incidents = client.meteor['incidents']

        iveris = incidents.aggregate([
            {"$match": {"tags": {"$exists": True}}},
            {"$unwind": "$tags"},
            {"$match": {"tags": {"$regex": ''}}},
            {"$project": {
                "dateOpened": 1,
                "tags": 1,
                "phase": 1,
                "_id": 0
            }}
        ])
        if iveris:
            return json.dumps(list(iveris), default=json_util.default)
        else:
            return json.dumps(list())
    except Exception as e:
            logger.error('Exception while aggregating veris summary: {0}\n'.format(e))


def initConfig():
    # output our log to stdout or syslog
    options.output = getConfig('output', 'stdout', options.configfile)
    options.sysloghostname = getConfig('sysloghostname', 'localhost', options.configfile)
    options.syslogport = getConfig('syslogport', 514, options.configfile)
    options.esservers = list(getConfig('esservers',
                                       'http://localhost:9200',
                                       options.configfile).split(','))

    # mongo connectivity options
    options.mongohost = getConfig('mongohost', 'localhost', options.configfile)
    options.mongoport = getConfig('mongoport', 3001, options.configfile)

    options.listen_host = getConfig('listen_host', '127.0.0.1', options.configfile)

    default_user_agent = 'Mozilla/5.0 (X11; Linux x86_64; rv:10.0) Gecko/20100101 Firefox/58.0'
    options.user_agent = getConfig('user_agent', default_user_agent, options.configfile)


parser = OptionParser()
parser.add_option(
    "-c",
    dest='configfile',
    default=os.path.join(os.path.dirname(__file__), __file__).replace('.py', '.conf'),
    help="configuration file to use")
(options, args) = parser.parse_args()
initConfig()
initLogger(options)
registerPlugins()

if __name__ == "__main__":
    run(host=options.listen_host, port=8081)
else:
    application = default_app()
