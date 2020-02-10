# homeassistant-home_connect

This is a HOME ASSISTANT component to read the states of a HOME CONNECT Oven, Dishwasher, Washer & Dryer. 
(Based on the BOSCH Dryer module from GKREITZ: https://github.com/gkreitz/homeassistant-bosch_dryer)

This will give you five sensors for each HOME CONNECT device you have:
- **door**: `open`, `close`, `locked`, or `unknown`. https://developer.home-connect.com/docs/status/door_state
- **program**: `cotton`, `synthetic`, ..., `unknown`. https://developer-staging.home-connect.com/docs/dryer/supported_programs_and_options
- **remaining**: time remaining in seconds, or unknown.
- **elapsed**: time elapsed in seconds, or unknown.
- **state**: `inactive`, `ready`, `run`, `finished`, ..., or `unavailable`. https://developer.home-connect.com/docs/status/operation_state

If the devicse is off/not connected to wifi, you'll get a **state** of `unavailable`` and the rest as ``unknown``.


## Installation
- Ensure your HOME CONNECT device is set up and working in the Home Connect app.
- Copy this folder to `<config_dir>/custom_components/home_connect/`.
- Create an account on https://developer.home-connect.com/.
- Register an application. Pick `Device flow` for OAuth flow.
- Once you start this sequence, you have 5 minutes to complete it (or you'll have to restart from here):
  - `export CLIENT_ID="YOUR_CLIENT_ID"`
  - `curl -X POST -H "Content-Type: application/x-www-form-urlencoded" -d "client_id=${CLIENT_ID}" https://api.home-connect.com/security/oauth/device_authorization | tee tmp.json`
  - Go to `verification_uri` in a browser, type in `user_code`. Log in using your (end user, not developer) Home Connect account and approve.
  - `export DEVICE_CODE=$(jq -r .device_code tmp.json)`
  - `curl -X POST -H "Content-Type: application/x-www-form-urlencoded" -d "grant_type=urn:ietf:params:oauth:grant-type:device_code&device_code=${DEVICE_CODE}&client_id=${CLIENT_ID}" https://api.home-connect.com/security/oauth/token | tee access_token.json`
  - `jq .refresh_token access_token.json`

Put the following in your home assistant config:
```
sensor:
  - platform: home_connect
    refresh_token: "YOUR_REFRESH_TOKEN"
```

## Usage
I used the custom component 'multiple-entity-row' to display the states of the HOME CONNECT devices. For better readable timer i am using a template sensor.

sensors.yaml
```
    hb_timer:
      friendly_name: "Oven remaining"
      value_template: >
          {% if states('sensor.siemens_hbXXXXXXX_state') == 'finished' %}
            FINISHED
          {% elif states('sensor.siemens_hbXXXXXXX_state') == 'inactive' %}
            OFF
          {% elif states('sensor.siemens_hbXXXXXXX_remaining') == 'unknown' %} 
            ...
          {% elif states('sensor.siemens_hbXXXXXXX_remaining') | float < 61 %}
            {{ states('sensor.siemens_hbXXXXXXX_remaining') + " sek" }}
          {% else %}
            {{ ((states('sensor.siemens_hbXXXXXXX_remaining') | float / 60) | round(0)) | string + " min" }}
          {% endif %}
```

ui-lovelace.yaml
```
  - entity: sensor.hb_timer #Template Sensor for a more readable time
    type: custom:multiple-entity-row
    icon: mdi:window-maximize
    name: Oven
    info:
        entity: sensor.siemens_hbXXXXXXX_state
        name: "Status:"
    primary:
      entity: sensor.siemens_hbXXXXXXX_program
      name: Program
    secondary:
      entity: sensor.siemens_hbXXXXXXX_door
      name: Door
    tertiary:
      entity: sensor.siemens_hbXXXXXXX_elapsed
      name: Runtime
```

## Remarks on the API
This is built using the Home Connect API, documented on https://developer.home-connect.com/. There is plenty in the API that is not exposed via this component. Using the API, one can also remote control the dryer, but I haven't figured out a use case for that yet. The API is a straightforward REST API with Oauth authentication. There's also a server-side event feed giving pretty quick updates. Originally, this module was just polling, but I figured it'd be fun to test out asyncio, so I rewrote the module to be async and cloud-push.

The API is a bit flakey, and tends to time out/return 504 during European evenings. Currently, this module retries forever, with an exponential backoff. I'll fix to something a tad better if/when I get sufficiently annoyed.
