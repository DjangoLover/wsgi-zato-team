# -*- coding: utf-8 -*-

"""
Copyright (C) 2013 Dariusz Suchojad <dsuch at zato.io>

Licensed under LGPLv3, see LICENSE.txt for terms and conditions.
"""

# stdlib
from datetime import datetime, timedelta
from decimal import Decimal

# bunch
from bunch import Bunch

# lxml
from lxml.objectify import fromstring

# retools
from retools.lock import Lock 

# Zato
from zato.server.service import Service

PAIRS_KEY = 'exchange:pairs'
RATES_PATTERN = 'exchange:rates:{}'
UPDATE_LOCK = 'exchange:update-lock'

# ##############################################################################

class GetRate(Service):
    """ Returns an exchange for given currencies and date. The date is optional
    and defaults to today.
    """
    class SimpleIO(object):
        input_required = ('code_from', 'code_to')
        input_optional = ('date',)
        output_optional = ('rate',)
        
    def handle(self):
        # If no date was give, assume today is needed
        date = self.request.input.date or str(datetime.utcnow().date())

        # Where to find the cached value in Redis
        pair = '{}{}'.format(self.request.input.code_from, self.request.input.code_to)
        cache_key  = RATES_PATTERN.format(pair)

        # Return the rate, assuming any was stored for input data at all
        self.response.payload.rate = self.kvdb.conn.hget(cache_key, date)

# ##############################################################################

class CreateExchangePair(Service):
    """ Registers a pair of curriencies with the cache so their exchange rate
    is periodically updated.
    """
    class SimpleIO(object):
        input_required = ('code_from', 'code_to')
        
    def handle(self):
        self.kvdb.conn.sadd(PAIRS_KEY, '{}{}'.format(
            self.request.input.code_from, self.request.input.code_to))
    
class DeleteExchangePair(Service):
    """ Deletes all information, including exchange rates, regarding a given
    pair of currencies.
    """
    class SimpleIO(object):
        input_required = ('code_from', 'code_to')

    def handle(self):
        # Deletes the pair first
        self.kvdb.conn.srem(PAIRS_KEY, '{}{}'.format(
            self.request.input.code_from, self.request.input.code_to))
    
class GetExchangePairs(Service):
    """ Returns all pairs of currencies registered with the cache.
    """
    class SimpleIO(object):
        output_optional = ('code_from', 'code_to')
        output_repeated = True
        
    def handle(self):
        for pair in sorted(self.kvdb.conn.smembers(PAIRS_KEY)):
            
            # pair is in format of USDEUR
            item = Bunch()
            item.code_from = pair[:3]
            item.code_to = pair[3:]
            
            self.response.payload.append(item)
    
# ##############################################################################

class DispatchUpdateCache(Service):
    """ Grabs all pairs of currencies to update exchange rates for
    and asynchonronously invokes a service for each pair in background.
    """
    def handle(self):
        for pair in self.kvdb.conn.smembers(PAIRS_KEY):
            self.invoke_async(UpdateCache.get_name(), {'pair': pair})

class UpdateCache(Service):
    """ Updates Redis cache for given currencies and date with data returned
    from a service which provides all the information from YQL.
    """
    class SimpleIO(object):
        input_required = ('pair',)
        
    def handle(self):
        
        # Grab a distributed lock so concurrent updates don't interfere with each other
        with Lock(UPDATE_LOCK):
            
            # We always use UTC
            today = str(datetime.utcnow().date())
            
            # Key in the cache that data concerning current date and given currencies
            # is stored under
            cache_key  = RATES_PATTERN.format(self.request.input.pair)
            
            # Fetch currently cached value, if any has been already stored at all
            old_value = Decimal(self.kvdb.conn.hget(cache_key, today) or 0)
            
            # Fetch new data from the backend
            response = self.invoke(FetchRates.get_name(), {'pair':self.request.input.pair})
            new_value = Decimal(response['response']['rate'])
            
            # Either use the new value directly (because there wasn't any old one)
            # or find the average of old and new one
            new_value = new_value if not old_value else (old_value+new_value)/2
            
            # Store the new value in cache
            self.kvdb.conn.hset(cache_key, today, new_value)
        
class TrimCache(Service):
    """ Removes parts of cache so it doesn't contain any entries regarding dates
    older than what was given on input.
    """
    def handle(self):
        
        # last_permitted is the earliest possible date to keep in the cache,
        # any values earlier than that one will be deleted.
        today = datetime.utcnow().date()
        last_permitted = str(today - timedelta(days=int(self.request.raw_request)))
        
        # Grab a distributed lock to safely update the contents of the cache
        with Lock(UPDATE_LOCK):
            
            # Values are deleted as part of an either-or transaction pipeline. 
            # Either all will be deleted or none will be.
            with self.kvdb.conn.pipeline() as p:
                
                # Find all pairs that need to be deleted and add them to pipeline
                for key in self.kvdb.conn.keys(RATES_PATTERN.format('*')):
                    for date in self.kvdb.conn.hkeys(key):
                        if date < last_permitted:
                            p.hdel(key, date)
                            
                            # Output message to logs so users understand
                            # there's some activity going on
                            self.logger.info('Deleting {}/{}'.format(key, date))
                            
                # Execute the whole transaction as a single unit
                p.execute()

# ##############################################################################

class FetchRates(Service):
    """ Fetches current exchange rate for curriences in a given pair,
    i.e. between USD and EUR.
    """
    class SimpleIO(object):
        input_required = ('pair',)
        output_required = ('rate',)
        
    def handle(self):
        
        # Fetch outgoing connections by its name
        out = self.outgoing.plain_http.get('YQL')
        
        # YQL query template
        q = 'select * from yahoo.finance.xchange where pair in ("{}")'
        
        # URL parameters to send
        params = {
            'q': q.format(self.request.input.pair), 
            'env': 'store://datatables.org/alltableswithkeys'
            }
        
        # Invoke Y! with newly built parameters and grab the response
        response = out.conn.get(self.cid, params)
        
        # Parse the XML into a Pythonic, easy to use, object
        root = fromstring(response.text.encode('utf-8'))
        
        # Assign to payload the rate from XML
        self.response.payload.rate = root.results.rate.Rate.text
        
# ##############################################################################
