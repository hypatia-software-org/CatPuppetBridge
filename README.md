# Developing

## Prerequisites

* An IRC Server to connect to (TODO: provide a simple server for development)
* A discord Guild you have administrative permissions on

## Developing

### Prerequesits

* A `Discord Server` to invite the bot to
* Python 3.x

### IRC Server for Testing

For testing we recommend using `irc.server` implementation for testing.

* Activate the virtualenv:
```source .venv/bin/activate```
* Start the irc server:
```python -m 'irc.server'```

### Create a Discord Bot

* Navigate to `https://discord.com/developers/applications/`
* Create a new application by clicking `New Application`
* Obtain your token by clicking `Bot` then `Reset Token` then finally `Copy` to copy it to your clipboard
* Save this token to add to the `catpuppet.ini` file detailed below (if you lose this, you will have to regenerate it)

### Invite bot to your Discord Server

* Navigate to `https://discord.com/developers/applications/`
* Click the bot you created in the previous step
* Click `OAuth2`
* Click `Add Redirect`
* Any URL can be added, if not sure what to use just use our GitHub `https://github.com/hypatia-software-org/CatPuppetBridge`
* Under `OAuth2 URL Generator` check the `bot` box
* Under `BOT PERMISSIONS` check:
  * `Send Messages`
  * `Add Reactions`
  * `Read Message History`
  * `Manage Webhooks`
* Under `GENERATED URL` click `Copy` to copy the URL
* Navigate to the URL you have copied to invite the bot to your guild

### Building

* Copy the default configuration:
```cp catbridge.ini.default catbridge.ini```
* Open `catbridge.ini` with your editor of choice and add your:
  * `Token` (generated in the `Create a Discord Bot` step above)
* Create a virtualenv
```virtualenv .venv```
* Activate the virtualenv
```source .venv/bin/activate```
* Install dependencies into the `virtualenv`
```pip install requirements/prod.txt```
* Run the bridge:
```python main.py```

# Contributing

* Issue Tracker: https://github.com/hypatia-software-org/CatPuppetBridge/issues
* IRC: [OFTC](https://www.oftc.net/) #catpuppetbridge

# License

* GPLv3: https://www.gnu.org/licenses/gpl-3.0.en.html#license-text
