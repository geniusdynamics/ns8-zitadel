# ns8-zitadel

[Zitadel](https://zitadel.com/) is an opensource Identity Infrastructure for organizations, with Multi tenancy Support.

[Docker Compose.](https://raw.githubusercontent.com/zitadel/zitadel/main/docs/docs/self-hosting/deploy/docker-compose.yaml)

This is a template module for [NethServer 8](https://github.com/NethServer/ns8-core).
## Install

Instantiate the module with:

    add-module ghcr.io/geniusdynamics/zidatel:latest 1

The output of the command will return the instance name.
Output example:

    {"module_id": "zidatel1", "image_name": "zidatel", "image_url": "ghcr.io/geniusdynamics/zidatel:latest"}

## Configure

Let's assume that the mattermost instance is named `zidatel1`.

Launch `configure-module`, by setting the following parameters:
- `host`: a fully qualified domain name for the application
- `http2https`: enable or disable HTTP to HTTPS redirection (true/false)
- `lets_encrypt`: enable or disable Let's Encrypt certificate (true/false)


Example:

```
api-cli run configure-module --agent module/zidatel1 --data - <<EOF
{
  "host": "zidatel.domain.com",
  "http2https": true,
  "lets_encrypt": false
}
EOF
```

The above command will:
- start and configure the zidatel instance
- configure a virtual host for trafik to access the instance

## Get the configuration
You can retrieve the configuration with

```
api-cli run get-configuration --agent module/zidatel1
```

## Uninstall

To uninstall the instance:

    remove-module --no-preserve zidatel1

## Smarthost setting discovery

Some configuration settings, like the smarthost setup, are not part of the
`configure-module` action input: they are discovered by looking at some
Redis keys.  To ensure the module is always up-to-date with the
centralized [smarthost
setup](https://geniusdynamics.github.io/ns8-core/core/smarthost/) every time
zidatel starts, the command `bin/discover-smarthost` runs and refreshes
the `state/smarthost.env` file with fresh values from Redis.

Furthermore if smarthost setup is changed when zidatel is already
running, the event handler `events/smarthost-changed/10reload_services`
restarts the main module service.

See also the `systemd/user/zidatel.service` file.

This setting discovery is just an example to understand how the module is
expected to work: it can be rewritten or discarded completely.

## Debug

some CLI are needed to debug

- The module runs under an agent that initiate a lot of environment variables (in /home/zidatel1/.config/state), it could be nice to verify them
on the root terminal

    `runagent -m zidatel1 env`

- you can become runagent for testing scripts and initiate all environment variables
  
    `runagent -m zidatel1`

 the path become : 
```
    echo $PATH
    /home/zidatel1/.config/bin:/usr/local/agent/pyenv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/usr/
```

## Testing

Test the module using the `test-module.sh` script:


    ./test-module.sh <NODE_ADDR> ghcr.io/geniusdynamics/zidatel:latest

The tests are made using [Robot Framework](https://robotframework.org/)

## UI translation

Translated with [Weblate](https://hosted.weblate.org/projects/ns8/).

To setup the translation process:

- add [GitHub Weblate app](https://docs.weblate.org/en/latest/admin/continuous.html#github-setup) to your repository
- add your repository to [hosted.weblate.org]((https://hosted.weblate.org) or ask a NethServer developer to add it to ns8 Weblate project
