# (C) Copyright 2005-2011 Nuxeo SAS <http://nuxeo.com>
# Author: bdelbosc@nuxeo.com
# Contributors: Tom Lazar
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published
# by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA
# 02111-1307, USA.
#
"""FunkLoad test case using Richard Jones' webunit.

$Id: FunkLoadTestCase.py 24757 2005-08-31 12:22:19Z bdelbosc $
"""
import os
import sys
import time
import re
import logging
from warnings import warn
from socket import error as SocketError
from types import DictType, ListType, TupleType
import unittest
import traceback
from random import random
from urllib import urlencode
from tempfile import mkdtemp
from urlparse import urljoin
from ConfigParser import ConfigParser, NoSectionError, NoOptionError
from contextlib import contextmanager
from funkload.log import get_results_logger

from webunit.webunittest import WebTestCase, HTTPError

import PatchWebunit
from utils import get_default_logger, mmn_is_bench, mmn_decode, Data
from utils import recording, thread_sleep, is_html, get_version, trace
from xmlrpclib import ServerProxy

_marker = []

RESPONSE_BY_STEP = "Request {step}.{number}: {type} - {url}"
RESPONSE_BY_DESCRIPTION = "{type} {url}: {description}"
PAGE = "{type} {url}: {description}"
TEST = "Test: {name}"

# ------------------------------------------------------------
# Classes
#
class FunkLoadTestCase(unittest.TestCase):
    """Unit test with browser and configuration capabilties."""
    # ------------------------------------------------------------
    # Initialisation
    #
    def __init__(self, methodName='runTest', options=None):
        """Initialise the test case.

        Note that methodName is encoded in bench mode to provide additional
        information like thread_id, concurrent virtual users..."""
        if mmn_is_bench(methodName):
            self.in_bench_mode = True
        else:
            self.in_bench_mode = False
        self.test_name, self.cycle, self.cvus, self.thread_id = mmn_decode(
            methodName)
        self.meta_method_name = methodName
        self.suite_name = self.__class__.__name__
        unittest.TestCase.__init__(self, methodName=self.test_name)
        self._response = None
        self._options = options
        self.debug_level = getattr(options, 'debug_level', 0)
        self._funkload_init()
        self._dump_dir = getattr(options, 'dump_dir', None)
        self._dumping =  self._dump_dir and True or False
        self._viewing = getattr(options, 'firefox_view', False)
        self._accept_invalid_links = getattr(options, 'accept_invalid_links',
                                             False)
        self._bench_label = getattr(options, 'label', None)
        self._stop_on_fail = getattr(options, 'stop_on_fail', False)
        self._pause = getattr(options, 'pause', False)
        self._keyfile_path = None
        self._certfile_path = None
        if self._viewing and not self._dumping:
            # viewing requires dumping contents
            self._dumping = True
            self._dump_dir = mkdtemp('_funkload')
        self._loop_mode = getattr(options, 'loop_steps', False)
        if self._loop_mode:
            if options.loop_steps.count(':'):
                steps = options.loop_steps.split(':')
                self._loop_steps = range(int(steps[0]), int(steps[1]))
            else:
                self._loop_steps = [int(options.loop_steps)]
            self._loop_number = options.loop_number
            self._loop_recording = False
            self._loop_records = []
        if sys.version_info >= (2, 5):
            self.__exc_info = sys.exc_info
        
        self._aggregates = []


    def _funkload_init(self):
        """Initialize a funkload test case using a configuration file."""
        # look into configuration file
        config_directory = os.getenv('FL_CONF_PATH', '.')
        config_path = os.path.join(config_directory,
                                   self.__class__.__name__ + '.conf')
        config_path = os.path.abspath(config_path)
        if not os.path.exists(config_path):
            config_path = "Missing: "+ config_path
        config = ConfigParser()
        config.read(config_path)
        self._config = config
        self._config_path = config_path
        self.default_user_agent = self.conf_get('main', 'user_agent',
                                                'FunkLoad/%s' % get_version(),
                                                quiet=True)
        if self.in_bench_mode:
            section = 'bench'
        else:
            section = 'ftest'
        self.setOkCodes( self.conf_getList(section, 'ok_codes',
                                           [200, 301, 302, 303, 307],
                                           quiet=True) )
        self.sleep_time_min = self.conf_getFloat(section, 'sleep_time_min', 0)
        self.sleep_time_max = self.conf_getFloat(section, 'sleep_time_max', 0)
        self._simple_fetch = self.conf_getInt(section, 'simple_fetch', 0, 
                                              quiet=True)
        self.log_to = self.conf_get(section, 'log_to', 'console file')
        self.log_path = self.conf_get(section, 'log_path', 'funkload.log')
        self.result_path = os.path.abspath(
            self.conf_get(section, 'result_path', 'funkload.xml'))

        # init loggers
        if self.in_bench_mode:
            level = logging.INFO
        else:
            level = logging.DEBUG
        self.logger = get_default_logger(self.log_to, self.log_path,
                                         level=level)
        self.logger_results = get_results_logger(self.result_path)

        #self.logd('_funkload_init config [%s], log_to [%s],'
        #          ' log_path [%s], result [%s].' % (
        #    self._config_path, self.log_to, self.log_path, self.result_path))

        # init webunit browser (passing a fake methodName)
        self._browser = WebTestCase(methodName='log')
        self.clearContext()

        #self.logd('# FunkLoadTestCase._funkload_init done')
    
    
    def setOkCodes(self, ok_codes):
        """Set ok codes."""
        self.ok_codes = map(int, ok_codes) 
    
    
    def clearContext(self):
        """Reset the testcase."""
        self._browser.clearContext()
        self._browser.css = {}
        self._browser.history = []
        self._browser.extra_headers = []
        if self.debug_level >= 3:
            self._browser.debug_headers = True
        else:
            self._browser.debug_headers = False
        self.test_status = 'Successful'
        self.steps = 0
        self.page_responses = 0
        self.total_responses = 0
        self.total_time = 0.0
        self.total_pages = self.total_images = 0
        self.total_links = self.total_redirects = 0
        self.total_xmlrpc = 0
        self.clearBasicAuth()
        self.clearHeaders()
        self.clearKeyAndCertificateFile()
        self.setUserAgent(self.default_user_agent)

        self.logdd('FunkLoadTestCase.clearContext done')



    #------------------------------------------------------------
    # browser simulation
    #
    def _connect(self, url, params, ok_codes, rtype, description, redirect=False):
        """Handle fetching, logging, errors and history."""
        if params is None and rtype in ('post','put'):
            # enable empty put/post
            params = []
        
        with self.record_response(rtype, url, description, redirect=redirect) as metadata:
            try:
                response = self._browser.fetch(url, params, ok_codes=ok_codes,
                                               key_file=self._keyfile_path,
                                               cert_file=self._certfile_path, method=rtype)
                metadata['test_status'] = 'Success'
                metadata['response_code'] = response.code

                if rtype in ('put', 'post', 'get', 'delete'):
                    # this is a valid referer for the next request
                    self.setHeader('Referer', url)
                self._browser.history.append((rtype, url))
                if self._dumping:
                    self._dump_content(response)
                return response

            except HTTPError as exc:
                if self._dumping:
                    self._dump_content(exc.response)
                raise

    def _browse(self, url_in, params_in=None,
                description=None, ok_codes=None,
                method='post',
                follow_redirect=True, load_auto_links=True,
                sleep=True):
        """Simulate a browser handle redirects, load/cache css and images."""
        self._response = None
        # Loop mode
        if self._loop_mode:
            if self.steps == self._loop_steps[0]:
                self._loop_recording = True
                self.logi('Loop mode start recording')
            if self._loop_recording:
                self._loop_records.append((url_in, params_in, description,
                                           ok_codes, method, follow_redirect,
                                           load_auto_links, False))
        # ok codes
        if ok_codes is None:
            ok_codes = self.ok_codes
        if type(params_in) is DictType:
            params_in = params_in.items()
        params = []
        if params_in:
            if isinstance(params_in, Data):
                params = params_in
            else:
                for key, value in params_in:
                    if type(value) is DictType:
                        for val, selected in value.items():
                            if selected:
                                params.append((key, val))
                    elif type(value) in (ListType, TupleType):
                        for val in value:
                            params.append((key, val))
                    else:
                        params.append((key, value))

        if method == 'get' and params:
            url = url_in + '?' + urlencode(params)
        else:
            url = url_in
        if method == 'get':
            params = None

        if method == 'get':
            if not self.in_bench_mode:
                self.logd('GET: %s\n\tPage %i: %s ...' % (url, self.steps,
                                                          description or ''))
        else:
            url = url_in
            if not self.in_bench_mode:
                self.logd('%s: %s %s\n\tPage %i: %s ...' % (
                        method.upper(), url, str(params),
                        self.steps, description or ''))
            # Fetching
        response = self._connect(url, params, ok_codes, method, description)

        # Check redirection
        if follow_redirect and response.code in (301, 302, 303, 307):
            max_redirect_count = 10
            thread_sleep()              # give a chance to other threads
            while response.code in (301, 302, 303, 307) and max_redirect_count:
                # Figure the location - which may be relative
                newurl = response.headers['Location']
                url = urljoin(url_in, newurl)
                # Save the current url as the base for future redirects
                url_in = url
                self.logd(' Load redirect link: %s' % url)
                # Use the appropriate method for redirection
                if response.code in (302, 303):
                    method = 'get'
                if response.code == 303:
                    # 303 is HTTP/1.1, make sure the connection 
                    # is not in keep alive mode
                    self.setHeader('Connection', 'close')
                response = self._connect(url, None, ok_codes, rtype=method,
                                         description=None, redirect=True)
                max_redirect_count -= 1
            if not max_redirect_count:
                self.logd(' WARNING Too many redirects give up.')

        # Load auto links (css and images)
        response.is_html = is_html(response.body)
        if load_auto_links and response.is_html and not self._simple_fetch:
            self.logd(' Load css and images...')
            page = response.body
            # pageImages is patched to call self.record on all links
            self._browser.pageImages(url, page, self)
        if sleep:
            self.sleep()
        self._response = response

        # Loop mode
        if self._loop_mode and self.steps == self._loop_steps[-1]:
            self._loop_recording = False
            self.logi('Loop mode end recording.')
            t_start = self.total_time
            count = 0
            for i in range(self._loop_number):
                self.logi('Loop mode replay %i' % i)
                for record in self._loop_records:
                    count += 1
                    self.steps += 1
                    self._browse(*record)
            t_delta = self.total_time - t_start
            text = ('End of loop: %d pages rendered in %.3fs, '
                    'avg of %.3fs per page, '
                    '%.3f SPPS without concurrency.' % (count, t_delta,
                                                        t_delta / count,
                                                        count/t_delta))
            self.logi(text)
            trace(text + '\n')

        return response

    def post(self, url, params=None, description=None, ok_codes=None, load_auto_links=True):
        """POST method on url with params."""
        self.steps += 1
        self.page_responses = 0
        response = self._browse(url, params, description, ok_codes,
                                method="post", load_auto_links=load_auto_links)
        return response

    def get(self, url, params=None, description=None, ok_codes=None, load_auto_links=True):
        """GET method on url adding params."""
        self.steps += 1
        self.page_responses = 0
        response = self._browse(url, params, description, ok_codes,
                                method="get", load_auto_links=load_auto_links)
        return response

    def method(self, method, url, params=None, description=None,
               ok_codes=None, load_auto_links=True):
        """Generic method request can be used to submit MOVE, MKCOL or
        whatever method name request."""
        self.steps += 1
        self.page_responses = 0
        response = self._browse(url, params, description, ok_codes,
                                method=method, load_auto_links=load_auto_links)
        return response

    def put(self, url, params=None, description=None, ok_codes=None,
            load_auto_links=True):
        """PUT method."""
        return self.method('put', url, params, description, ok_codes, 
                load_auto_links=load_auto_links)

    def delete(self, url, description=None, ok_codes=None):
        """DELETE method on url."""
        return self.method('delete', url, None, description, ok_codes)

    def head(self, url, description=None, ok_codes=None):
        """HEAD method on url adding params."""
        return self.method('head', url, None, description, ok_codes)

    def options(self, url, description=None, ok_codes=None):
        """OPTIONS method on url."""
        return self.method('options', url, None, description, ok_codes)

    def propfind(self, url, params=None, depth=None, description=None,
                 ok_codes=None):
        """DAV PROPFIND method."""
        if ok_codes is None:
            codes = [207, ]
        else:
            codes = ok_codes
        if depth is not None:
            self.setHeader('depth', str(depth))
        ret = self.method('PROPFIND', url, params=params,
                          description=description, ok_codes=codes)
        if depth is not None:
            self.delHeader('depth')
        return ret

    def exists(self, url, params=None, description="Checking existence"):
        """Try a GET on URL return True if the page exists or False."""
        resp = self.get(url, params, description=description,
                        ok_codes=[200, 301, 302, 303, 307, 404, 503], load_auto_links=False)
        if resp.code not in [200, 301, 302, 303, 307]:
            self.logd('Page %s not found.' % url)
            return False
        return True

    def xmlrpc(self, url_in, method_name, params=None, description=None):
        """Call an xml rpc method_name on url with params."""
        self.steps += 1
        self.page_responses = 0
        self.logd('XMLRPC: %s::%s\n\tCall %i: %s ...' % (url_in, method_name,
                                                         self.steps,
                                                         description or ''))
        response = None
        if self._authinfo is not None:
            url = url_in.replace('//', '//'+self._authinfo)
        else:
            url = url_in
        
        method_url = url_in + "#" + method_name
        with self.record_response('xmlrpc', method_url, description):
            server = ServerProxy(url)
            method = getattr(server, method_name)
            if params is not None:
                response = method(*params)
            else:
                response = method()
            self.sleep()
            return response

    def xmlrpc_call(self, url_in, method_name, params=None, description=None):
        """BBB of xmlrpc, this method will be removed for 1.6.0."""
        warn('Since 1.4.0 the method "xmlrpc_call" is renamed into "xmlrpc".',
             DeprecationWarning, stacklevel=2)
        return self.xmlrpc(url_in, method_name, params, description)

    def waitUntilAvailable(self, url, time_out=20, sleep_time=2):
        """Wait until url is available.

        Try a get on url every sleep_time until server is reached or
        time is out."""
        time_start = time.time()
        while(True):
            try:
                self._browser.fetch(url, None,
                                    ok_codes=[200, 301, 302, 303, 307],
                                    key_file=self._keyfile_path,
                                    cert_file=self._certfile_path, method="get")
            except SocketError:
                if time.time() - time_start > time_out:
                    self.fail('Time out service %s not available after %ss' %
                              (url, time_out))
            else:
                return
            time.sleep(sleep_time)

    def setBasicAuth(self, login, password):
        """Set HTTP basic authentication for the following requests."""
        self._browser.setBasicAuth(login, password)
        self._authinfo = '%s:%s@' % (login, password)

    def clearBasicAuth(self):
        """Remove basic authentication."""
        self._browser.clearBasicAuth()
        self._authinfo = None

    def addHeader(self, key, value):
        """Add an http header."""
        self._browser.extra_headers.append((key, value))

    def setHeader(self, key, value):
        """Add or override an http header.

        If value is None, the key is removed."""
        headers = self._browser.extra_headers
        for i, (k, v) in enumerate(headers):
            if k == key:
                if value is not None:
                    headers[i] = (key, value)
                else:
                    del headers[i]
                break
        else:
            if value is not None:
                headers.append((key, value))

    def delHeader(self, key):
        """Remove an http header key."""
        self.setHeader(key, None)

    def clearHeaders(self):
        """Remove all http headers set by addHeader or setUserAgent.

        Note that the Referer is also removed."""
        self._browser.extra_headers = []

    def debugHeaders(self, debug_headers=True):
        """Print request headers."""
        self._browser.debug_headers = debug_headers

    def setUserAgent(self, agent):
        """Set User-Agent http header for the next requests.

        If agent is None, the user agent header is removed."""
        self.setHeader('User-Agent', agent)

    def sleep(self):
        """Sleeps a random amount of time.

        Between the predefined sleep_time_min and sleep_time_max values.
        """
        if self._pause:
            raw_input("Press ENTER to continue ")
            return
        s_min = self.sleep_time_min
        s_max = self.sleep_time_max
        if s_max != s_min:
            s_val = s_min + abs(s_max - s_min) * random()
        else:
            s_val = s_min
        # we should always sleep something
        thread_sleep(s_val)

    def setKeyAndCertificateFile(self, keyfile_path, certfile_path):
        """Set the paths to a key file and a certificate file that will be
        used by a https (ssl/tls) connection when calling the post or get
        methods.

        keyfile_path : path to a PEM formatted file that contains your
        private key.
        certfile_path : path to a PEM formatted certificate chain file.
        """
        self._keyfile_path = keyfile_path
        self._certfile_path = certfile_path

    def clearKeyAndCertificateFile(self):
        """Clear any key file or certificate file paths set by calls to
        setKeyAndCertificateFile.
        """
        self._keyfile_path = None
        self._certfile_path = None


    #------------------------------------------------------------
    # Assertion helpers
    #
    def getLastUrl(self):
        """Return the last accessed url taking into account redirection."""
        response = self._response
        if response is not None:
            return response.url
        return ''

    def getBody(self):
        """Return the last response content."""
        response = self._response
        if response is not None:
            return response.body
        return ''

    def listHref(self, url_pattern=None, content_pattern=None):
        """Return a list of href anchor url present in the last html response.

        Filtering href with url pattern or link text pattern."""
        response = self._response
        ret = []
        if response is not None:
            a_links = response.getDOM().getByName('a')
            if a_links:
                for link in a_links:
                    try:
                        ret.append((link.getContentString(), link.href))
                    except AttributeError:
                        pass
            if url_pattern is not None:
                pat = re.compile(url_pattern)
                ret = [link for link in ret
                       if pat.search(link[1]) is not None]
            if content_pattern is not None:
                pat = re.compile(content_pattern)
                ret = [link for link in ret
                       if link[0] and (pat.search(link[0]) is not None)]
        return [link[1] for link in ret]

    def getLastBaseUrl(self):
        """Return the base href url."""
        response = self._response
        if response is not None:
            base = response.getDOM().getByName('base')
            if base:
                return base[0].href
        return ''


    #------------------------------------------------------------
    # configuration file utils
    #
    def conf_get(self, section, key, default=_marker, quiet=False):
        """Return an entry from the options or configuration file."""
        # check for a command line options
        opt_key = '%s_%s' % (section, key)
        opt_val = getattr(self._options, opt_key, None)
        if opt_val:
            #print('[%s] %s = %s from options.' % (section, key, opt_val))
            return opt_val
        # check for the configuration file if opt val is None
        # or nul
        try:
            val = self._config.get(section, key)
        except (NoSectionError, NoOptionError):
            if not quiet:
                self.logi('[%s] %s not found' % (section, key))
            if default is _marker:
                raise
            val = default
        #print('[%s] %s = %s from config.' % (section, key, val))
        return val

    def conf_getInt(self, section, key, default=_marker, quiet=False):
        """Return an integer from the configuration file."""
        return int(self.conf_get(section, key, default, quiet))

    def conf_getFloat(self, section, key, default=_marker, quiet=False):
        """Return a float from the configuration file."""
        return float(self.conf_get(section, key, default, quiet))

    def conf_getList(self, section, key, default=_marker, quiet=False,
                     separator=None):
        """Return a list from the configuration file."""
        value = self.conf_get(section, key, default, quiet)
        if value is default:
            return value
        if separator is None:
            separator = ':'
        if value.count(separator):
            return value.split(separator)
        return [value]



    #------------------------------------------------------------
    # Extend unittest.TestCase to provide bench cycle hook
    #
    def setUpCycle(self):
        """Called on bench mode before a cycle start."""
        pass

    def tearDownCycle(self):
        """Called after a cycle in bench mode."""
        pass

    #------------------------------------------------------------
    # Extend unittest.TestCase to provide bench setup/teardown hook
    #
    def setUpBench(self):
        """Called before the start of the bench."""
        pass

    def tearDownBench(self):
        """Called after a the bench."""
        pass



    #------------------------------------------------------------
    # logging
    #
    def logd(self, message):
        """Debug log."""
        self.logger.debug(self.meta_method_name +': ' +message)

    def logdd(self, message):
        """Verbose Debug log."""
        if self.debug_level >= 2:
            self.logger.debug(self.meta_method_name +': ' +message)

    def logi(self, message):
        """Info log."""
        if hasattr(self, 'logger'):
            self.logger.info(self.meta_method_name+': '+message)
        else:
            print self.meta_method_name+': '+message

    def _open_result_log(self, **kw):
        """Open the result log."""
        self.logger_results.start_log()
        self.addMetadata(ns=None, **kw)

    def addMetadata(self, ns="meta", **kw):
        """Add metadata info."""
        for key, value in kw.items():
            self.logger_results.config(key, value, ns)

    def _close_result_log(self):
        """Close the result log."""
        self.logger_results.end_log()

    @contextmanager
    def record_response(self, rtype, url, description, **attrs):
        """
        A context manager that :py:func:`record`s  an http request to the
        specified url. In the case of an HTTPError, the `body`, `headers`,
        `result`, and `response_code` are stored in the record metadata, and
        the exception is re-raised.

        Each request is aggregated under the headings 'Response by step' and
        'Response by description'. The former uses the current request step
        and number to separated the responses, and the latter uses the supplied
        description.

        In this context, a new `step` is started for each top level HTTP operation
        initiated by the test, and by xmlrpc calls

        `rtype`:
            The http request type (for example: get, post, xmlrpc)
            
            Stored as `rtype` in the logged record

        `url`:
            The url to which this request is being made

            Stored as `url` in the logged record

        `description`:
            The description of this request

            Stored as `description` in the logged record

        `attrs`:
            Any additional named attributes to be stored on the logged record
        """
        step = self.steps
        number = self.page_responses
        with self.record({'Response by step': RESPONSE_BY_STEP.format(
                              step=step, number=number, type=rtype, url=url),
                          'Response by description': RESPONSE_BY_DESCRIPTION.format(
                              type=rtype, url=url, description=description)},
                          url=url, rtype=rtype, description=description,
                           **attrs) as metadata:
            try:
                self.page_responses += 1
                yield metadata
            except HTTPError as exc:
                metadata['body'] = exc.response.body
                metadata['headers'] = "\n".join(": ".join(header) for header in exc.response.headers.items())
                metadata['result'] = 'Failure'
                metadata['response_code'] = exc.response.code
                raise self.failureException, str(exc.response)

    @contextmanager
    def record(self, aggregates, **metadata):
        """
        A context manager that logs a timing record to the results logger.

        This record contains the cycle, cvus, thread_id, test suite_name,
        test_name, time, and duration of the contained block of code.

        If the bench is currently in startup mode (not all threads have
        begun executing), then this record will be marked with startup=True,
        and ignored by the default report builder.

        The contextmanager returns the `metadata` dictionary, and when recording
        the record, writes all contents of the `metadata` dictionary as children
        of the record element. The only `metadata` keys used by the report builder
        are 'result' and 'traceback'. If 'result' != 'Successful', the report builder
        considers that record to have failed. 'result' defaults to 'Successful' but
        can be changed by the test contents.
        
        If the executed code block raises an exception, 'result' is set to 'Error'
        and 'traceback' is set to the formatted exception traceback of the raised
        exception. The exception is then re-raised.

        `aggregates`: dict
            This is a dictionary mapping top level aggregation keys to their values.
            The top level keys will be used to create sections in the built report,
            and the value will be used to create subsections. The sections will
            report stats for all records with that aggregate key, and the subsections
            will report stats for all records with the aggregate value.

        `**metadata`:
            Any named arguments to record will be stored as children of the record
            element in the results log xml

        
        """
        info = {}
        info['cycle'] = str(self.cycle)
        info['cvus'] = str(self.cvus)
        info['thread_id'] = str(self.thread_id)
        info['suite_name'] = str(self.suite_name)
        info['test_name'] = str(self.test_name)
        start_time = time.time()
        try:
            metadata['result'] = 'Successful'
            yield metadata

        except KeyboardInterrupt:
            raise
        except:
            metadata['result'] = 'Error'
            metadata['traceback'] = ' '.join(
                traceback.format_exception(*sys.exc_info()))
            raise
        finally:
            if self.in_bench_mode and not recording():
                info['startup'] = True
            info['time'] = str(start_time)
            info['duration'] = str(time.time() - start_time)
            self.logger_results.record(info, metadata, aggregates)

    def _dump_content(self, response):
        """Dump the html content in a file.

        Use firefox to render the content if we are in rt viewing mode."""
        dump_dir = self._dump_dir
        if dump_dir is None:
            return
        if getattr(response, 'code', 301) in [301, 302, 303, 307]:
            return
        if not response.body:
            return
        if not os.access(dump_dir, os.W_OK):
            os.mkdir(dump_dir, 0775)
        content_type = response.headers.get('content-type')
        if content_type == 'text/xml':
            ext = '.xml'
        else:
            ext = os.path.splitext(response.url)[1]
            if not ext.startswith('.') or len(ext) > 4:
                ext = '.html'
        file_path = os.path.abspath(
            os.path.join(dump_dir, '%3.3i%s' % (self.steps, ext)))
        f = open(file_path, 'w')
        f.write(response.body)
        f.close()
        if self._viewing:
            cmd = 'firefox -remote  "openfile(file://%s,new-tab)"' % file_path
            ret = os.system(cmd)
            if ret != 0:
                self.logi('Failed to remote control firefox: %s' % cmd)
                self._viewing = False


    #------------------------------------------------------------
    # Overriding unittest.TestCase
    #
    def __call__(self, result=None):
        """Run the test method.

        Override to log test result."""
        if result is None:
            result = self.defaultTestResult()
        result.startTest(self)
        if sys.version_info >= (2, 5):
            methodName = self._testMethodName
        else:
            methodName = self._TestCase__testMethodName
        testMethod = getattr(self, methodName)
        try:
            with self.record({'Test': methodName}) as metadata:
                ok = False
                if not self.in_bench_mode:
                    self.logd('Starting -----------------------------------\n\t%s'
                              % self.conf_get(self.meta_method_name, 'description', ''))
                self.setUp()
                try:
                    testMethod()
                    ok = True
                except self.failureException:
                    result.addFailure(self, self.__exc_info())
                    metadata['result'] = 'Failure'
                    ok = False

                self.tearDown()

                if ok:
                    result.addSuccess(self)
        except KeyboardInterrupt:
            raise
        except:
            result.addFailure(self, self.__exc_info())
            metadata['result'] = 'Error'
            metadata['traceback'] = ' '.join(
                traceback.format_exception(*sys.exc_info()))

        finally:
            if not ok and self._stop_on_fail:
                result.stop()
            result.stopTest(self)




# ------------------------------------------------------------
# testing
#
class DummyTestCase(FunkLoadTestCase):
    """Testing Funkload TestCase."""

    def test_apache(self):
        """Simple apache test."""
        self.logd('start apache test')
        for i in range(2):
            self.get('http://localhost/')
            self.logd('base_url: ' + self.getLastBaseUrl())
            self.logd('url: ' + self.getLastUrl())
            self.logd('hrefs: ' + str(self.listHref()))
        self.logd("Total connection time = %s" % self.total_time)

if __name__ == '__main__':
    unittest.main()

