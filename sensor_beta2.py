import logging
import json
import datetime
import asyncio

from homeassistant.components.sensor import PLATFORM_SCHEMA
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle
from homeassistant.const import (STATE_UNAVAILABLE, STATE_UNKNOWN)

from homeassistant.helpers import aiohttp_client

_LOGGER = logging.getLogger(__name__)
REQUIREMENTS = ['aiohttp-sse-client==0.1.6', 'aiohttp==3.5.4']

DOMAIN = 'home_connect'

CONF_REFRESH_TOKEN = 'refresh_token'
CONF_TOKEN = 'bearer_token'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_REFRESH_TOKEN): cv.string,
})

OVEN_SENSORS = ['OperationState', 'DoorState', 'LocalControlActive', 'Program', 'Elapsed', 'Remaining', 'Progress', 'Warning']
DISHWASHER_SENSORS = ['OperationState', 'DoorState', 'LocalControlActive', 'Program', 'Remaining', 'Progress', 'Warning']
WASHER_SENSORS = ['OperationState', 'DoorState', 'LocalControlActive', 'Program', 'Elapsed', 'Remaining', 'Temperature', 'SpinSpeed', 'Warning']
DRYER_SENSORS = ['OperationState', 'DoorState', 'LocalControlActive', 'Program', 'Elapsed', 'Remaining', 'Warning']
COFFEEMAKER_SENSORS = ['OperationState', 'LocalControlActive', 'Program', 'Elapsed', 'Remaining', 'BeanAmount', 'FillQuantity', 'Temperature', 'Warning']
FREEZER_SENSORS = ['OperationState', 'DoorState', 'Warning']
FRIDGEFREEZER_SENSORS = ['OperationState', 'DoorState', 'Warning']
REFRIGERATOR_SENSORS = ['OperationState', 'DoorState', 'Warning']
WINECOOLER_SENSORS = ['OperationState', 'DoorState', 'Warning']
BASE_URL = 'https://api.home-connect.com/'


def _build_api_url(suffix, haId=None):
    base_url = BASE_URL + 'api/'
    if suffix[0] == '/':
        suffix = suffix[1:]
    return base_url + suffix.format(haid=haId)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    from aiohttp_sse_client import client as sse_client
    import aiohttp
    import multidict

    _LOGGER.debug("Starting HOME CONNECT sensor")

    session = aiohttp_client.async_get_clientsession(hass)
    auth_session = OauthSession(session, config.get(CONF_REFRESH_TOKEN))

    headers = {'Accept': 'application/vnd.bsh.sdk.v1+json'}
    appliances_response = await auth_session.get(_build_api_url('/homeappliances'), headers=headers)
    appliances = appliances_response['data']['homeappliances']

    for a in appliances:
        _LOGGER.debug('Found device %s', a)
        if a['type'] not in ['Oven','Dryer','Washer','Dishwasher','CoffeeMaker','Freezer','FridgeFreezer','Refrigerator','Wine-cooler']:
            continue

        haId = a['haId']
        _LOGGER.info('Found device %s', haId)
        reader = HCDataReader(auth_session, a['haId'], hass)
        hass.loop.create_task(reader.process_updates())
        if a['type'] == "Oven":
            async_add_entities([HCSensorEntity(reader, key, a['brand'], a['vib'], key.capitalize()) for key in OVEN_SENSORS])
        elif a['type'] == "Dryer":
            async_add_entities([HCSensorEntity(reader, key, a['brand'], a['vib'], key.capitalize()) for key in DRYER_SENSORS])
        elif a['type'] == "Washer":
            async_add_entities([HCSensorEntity(reader, key, a['brand'], a['vib'], key.capitalize()) for key in WASHER_SENSORS])
        elif a['type'] == "Dishwasher":
            async_add_entities([HCSensorEntity(reader, key, a['brand'], a['vib'], key.capitalize()) for key in DISHWASHER_SENSORS])
        elif a['type'] == "CoffeeMaker":
            async_add_entities([HCSensorEntity(reader, key, a['brand'], a['vib'], key.capitalize()) for key in COFFEEMAKER_SENSORS])
        elif a['type'] == "Freezer":
            async_add_entities([HCSensorEntity(reader, key, a['brand'], a['vib'], key.capitalize()) for key in FREEZER_SENSORS])            
        elif a['type'] == "FridgeFreezer":
            async_add_entities([HCSensorEntity(reader, key, a['brand'], a['vib'], key.capitalize()) for key in FRIDGEFREEZER_SENSORS])
        elif a['type'] == "Refrigerator":
            async_add_entities([HCSensorEntity(reader, key, a['brand'], a['vib'], key.capitalize()) for key in REFRIGERATOR_SENSORS])
        elif a['type'] == "Wine-cooler":
            async_add_entities([HCSensorEntity(reader, key, a['brand'], a['vib'], key.capitalize()) for key in WINECOOLER_SENSORS])
            
class OauthSession:
    def __init__(self, session, refresh_token):
        self._session = session
        self._refresh_token = refresh_token
        self._access_token = None
        self._fetching_new_token = None

    @property
    def session(self):
        return self._session

    async def token(self, old_token=None):
        """ Returns an authorization header. If one is supplied as old_token, invalidate that one """
        if self._access_token not in (None, old_token):
            return self._access_token

        if self._fetching_new_token is not None:
            await self._fetching_new_token.wait()
            return self._access_token

        self._access_token = None
        self._fetching_new_token = asyncio.Event()
        data = { 'grant_type': 'refresh_token', 'refresh_token': self._refresh_token }
        _LOGGER.debug('data: %s', data)
        refresh_response = await self._http_request(BASE_URL + 'security/oauth/token', 'post', data=data)
        if not 'access_token' in refresh_response:
            _LOGGER.error('OAuth token refresh did not yield access token! Got back %s', refresh_response)
        else:
            self._access_token = 'Bearer ' + refresh_response['access_token']

        self._fetching_new_token.set()
        self._fetching_new_token = None
        return self._access_token

    async def get(self, url, **kwargs):
        return await self._http_request(url, auth_token=self, **kwargs)

    async def _http_request(self, url, method='get', auth_token=None, headers={}, **kwargs):
        _LOGGER.debug('Making http %s request to %s, headers %s', method, url, headers)
        headers = headers.copy()
        tries = 0
        while True:
            if auth_token != None:
                # Cache token so we know which token was used for this request,
                # so we know if we need to invalidate.
                token = await auth_token.token()
                headers['Authorization'] = token
            try:
                async with self._session.request(method, url, headers=headers, **kwargs) as response:
                    _LOGGER.debug('Http %s request to %s got response %d', method, url, response.status)
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 404:
                        return await response.json()
                    elif response.status == 401 and auth_token != None:
                        _LOGGER.debug('Request to %s returned status %d, refreshing auth token', url, response.status)
                        token = await auth_token.token(token)
                    else:
                        _LOGGER.debug('Request to %s returned status %d', url, response.status)
            except Exception as e:
                _LOGGER.debug('Exception for http %s request to %s: %s', method, url, e)
            tries += 1
            await asyncio.sleep(min(600, 2**tries))


class HCDataReader:
    def __init__(self, auth_session, haId, hass):
        self._auth_session = auth_session
        self._haId = haId
        self._state = {}
        self._sensors = []
        self._hass = hass

    def register_sensor(self, sensor):
        self._sensors.append(sensor)

    def handle_key_value(self, key, value):
        updated = True
        if key == 'DISCONNECTED':
            self._state['OperationState'] = 'disconnected'
            if 'DoorState' in self._state:
                self._state['DoorState'] = ''
            if 'Program' in self._state:
                self._state['Program'] = ''
            if 'Remaining' in self._state:
                self._state['Remaining'] = ''
            if 'Elapsed' in self._state:
                self._state['Elapsed'] = ''
            if 'Warning' in self._state:
                self._state['Warning'] = ''
        elif key == 'BSH.Common.Status.DoorState':
            self._state['DoorState'] = value.rsplit('.',1)[1].lower()
        elif key == 'BSH.Common.Status.OperationState':
            self._state['OperationState'] = value.rsplit('.',1)[1].lower()
        elif key == 'BSH.Common.Setting.PowerState':
            self._state['OperationState'] = value.rsplit('.',1)[1].lower()
        elif key == 'BSH.Common.Root.ActiveProgram':
            if value.count('.') > 0:
                self._state['Program'] = value.rsplit('.',1)[1].lower()
            else:
                self._state['Program'] = value.lower()
        elif key == 'BSH.Common.Option.RemainingProgramTime':
            self._state['Remaining'] = int(value)
        elif key == 'BSH.Common.Option.ElapsedProgramTime':
            self._state['Elapsed'] = int(value)
        elif key == 'BSH.Common.Root.SelectedProgram':
            if value.count('.') > 0:
                self._state['Program'] = value.rsplit('.',1)[1].lower()
            else:
                self._state['Program'] = value.lower()
        elif key == 'BSH.Common.Option.ProgramProgress':
            self._state['Progress'] = int(value)
        elif key == 'ConsumerProducts.CoffeeMaker.Event.BeanContainerEmpty':
            self._state['Warning'] = 'bean container empty'
        elif key == 'ConsumerProducts.CoffeeMaker.Event.WaterTankEmpty':
            self._state['Warning'] = 'water tank empty'
        elif key == 'ConsumerProducts.CoffeeMaker.Event.DripTrayFull':
            self._state['Warning'] = 'drip tray full'
        elif key == 'ConsumerProducts.CoffeeMaker.Option.CoffeeTemperature':
            self._state['Temperature'] = int(value)
        elif key == 'ConsumerProducts.CoffeeMaker.Option.FillQuantity':
            self._state['FillQuantity'] = int(value)
        elif key == 'ConsumerProducts.CoffeeMaker.Option.BeanAmount':
            self._state['BeanAmount'] = int(value)
        elif key == 'Refrigeration.FridgeFreezer.Event.DoorAlarmFreezer':
            self._state['Warning'] = 'door alarm'
        elif key == 'Refrigeration.FridgeFreezer.Event.DoorAlarmRefrigerator':
            self._state['Warning'] = 'door alarm'
        elif key == 'Refrigeration.FridgeFreezer.Event.TemperatureAlarmFreezer':
            self._state['Warning'] = 'freezer temp too high'
        elif key == 'BSH.Common.Option.ProgramProgress':
            self._state['Progress'] = int(value)
        else:
            _LOGGER.debug('Ignored key-value pair: %s,%s', key, value)
            updated = False

        if updated:
            for sensor in self._sensors:
                sensor.async_schedule_update_ha_state()

    async def process_updates(self):
        from aiohttp_sse_client import client as sse_client
        from aiohttp import ClientTimeout

        _LOGGER.debug('Starting sse reader')
        token = await self._auth_session.token()
        headers = {'Accept-Language': 'en-US', 'Authorization': token}
        tries = 0

        while True:
            try:
                async with sse_client.EventSource(
                        _build_api_url('/homeappliances/{haid}/events', self._haId),
                        session=self._auth_session.session,
                        headers=headers,
                        timeout=ClientTimeout(total=None)
                ) as event_source:
                    self._hass.async_create_task(self.fetch_initial_state())
                    async for event in event_source:
                        tries = 0 # Reset backoff if we read any event successfully
                        if event.type != 'KEEP-ALIVE':
                            _LOGGER.debug('Received event: %s', event)
                        if event.data:
                            try:
                                data = json.loads(event.data)
                                for item in data['items']:
                                    if 'key' in item and 'value' in item:
                                        self.handle_key_value(item['key'], item['value'])
                            except  Exception as e:
                                _LOGGER.debug('SSE reader failed parsing %s', event.data)
                        elif event.type == 'DISCONNECTED':
                            self.handle_key_value('DISCONNECTED', '')
                            pass
                        elif event.type == 'CONNECTED':
                            self._hass.async_create_task(self.fetch_initial_state())
                            pass
            except ConnectionError as ce:
                _LOGGER.debug('SSE reader caught connection error: %s', ce)
                if '401' in ce.args[0]: # Ugly way to extract http status
                    _LOGGER.debug('Fetching new access token')
                    token = await self._auth_session.token(headers['Authorization'])
                    headers['Authorization'] = token
                tries += 1
            except Exception as e:
                _LOGGER.debug('SSE reader caught exception: %s', e)
                tries += 1
            await asyncio.sleep(min(600, 2**tries))

    @property
    def haId(self):
        """ returns the hardware Identifier """
        return self._haId

    def get_data(self, key):
        if key in self._state:
            return self._state[key]
        return STATE_UNKNOWN

    async def fetch_initial_state(self):
        _LOGGER.debug("Fetching initial state")

        headers = {'Accept': 'application/vnd.bsh.sdk.v1+json'}
        state_response = await self._auth_session.get(_build_api_url('/homeappliances/{haid}', self._haId), headers=headers)
        if not state_response['data']['connected']:
            self.handle_key_value('DISCONNECTED', '')
            return

        status_response = await self._auth_session.get(_build_api_url('/homeappliances/{haid}/status', self._haId), headers=headers)
        for item in status_response['data']['status']:
            self.handle_key_value(item['key'], item['value'])

        _LOGGER.debug('Actual state: %s', self.get_data('state'))
        if self.get_data('state') not in ['inactive', 'ready', 'finished']:
            program_response = await self._auth_session.get(_build_api_url('/homeappliances/{haid}/programs/active', self._haId), headers=headers)
            if 'error' in program_response:
                if program_response['error']['key'] == 'SDK.Error.NoProgramSelected':
                    self.handle_key_value('BSH.Common.Root.SelectedProgram', 'No program selected')
            elif 'data' in program_response:
                self.handle_key_value('BSH.Common.Root.SelectedProgram', program_response['data']['key'])
                for item in program_response['data']['options']:
                    self.handle_key_value(item['key'], item['value'])
        else:
            program_response = await self._auth_session.get(_build_api_url('/homeappliances/{haid}/programs/selected', self._haId), headers=headers)
            _LOGGER.debug('Program_response: %s', str(program_response))
            if 'error' in program_response:
                if program_response['error']['key'] == 'SDK.Error.NoProgramSelected':
                    self.handle_key_value('BSH.Common.Root.SelectedProgram', 'No program selected')
            elif 'data' in program_response:
                self.handle_key_value('BSH.Common.Root.SelectedProgram', program_response['data']['key'])

class HCSensorEntity(Entity):
    def __init__(self, reader, key, brand, vib, name):
        self._reader = reader
        self._key = key
        self._brand = brand
        self._vib = vib
        self._name = name
        self._reader.register_sensor(self)

    @property
    def unique_id(self):
        return '{}-{}'.format(self._reader.haId, self._name)

    @property
    def name(self):
        return '{} {} {}'.format(self._brand, self._vib, self._name)

    @property
    def state(self):
        return self._reader.get_data(self._key)

    @property
    def should_poll(self):
        return False
