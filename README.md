# Scripts

Useful shiz for developing Unikorn.

## Prerequisites

* GNU `make`
* `go`
* `kubectl`
* `jq`
* `yq`
* `column`

## Scripts

### build

Most useful script, this builds the binaries on your local machine, tags them with the most recent version defined in the Helm chart, and pushed them into KinD.

### deploy

Second most useful script, this deploys the component to KinD.
You will need to provide Helm values files to override default behaviour, which will be broken.
Only restarts all services if the Helm chart version has changed, or their pod templates have.

Deployments are usually useless without Helm `values.yaml` files.
These are located in `~/.config/unikorn/local` by default, and should be named after the service e.g. `core.yaml`, `identity.yaml` and so on (derived from the chart directory).
A special `global.yaml` file allows global parameters to be set for all deployments.

The deploy command has the following flags that may be of use:

* `-e <environment>` choose the environment to use defined in `~/.config/unikorn/${environment}` when looking up values files.
* `-t` dump the deployment out as raw resources, useful for piping into `kubectl diff -f -` to make sure nothing untoward has changed.
* `-p` do a production deployment using the actual helm repository, as opposed to the local source tree.

### restart

Like `deploy`, but just deletes all the pods.
This is used when a deploy would do nothing, e.g. the pod images or arguments have't changed but you have a new functional change pushed with `build`.

### release

Uses the canonical version in Chart.yaml to tag and push, creating a release.

### ui-preview

UI developer mode script, which has live reload and debug information readily available in your browser.
You will need to define a few environment variables for your setup, see the code of details.

### clean-images

Docker images are big, and if you are compiling 20 a day, that's a lot of space.
This deletes any danging images.

### uv

Display all deployed versions.

## Typical Usage

Fresh install:

```shell
build && deploy
```

Test a functional change:

```shell
build && restart
```

## Installation

Run:

```shell
make install
```

**NOTE**: This defaults to ~/bin, you can set `PREFIX` to modify this.

## Contribution

Be aware you need to run `shellcheck` and pass before acceptance.
