# Debian, not Alpine, and that is the whole reason this file differs from the
# other add-ons here: Bambu Studio for Linux is an AppImage built against
# glibc on Ubuntu 22.04, and Alpine's musl cannot run it. Bookworm's glibc
# (2.36) is newer than 22.04's (2.35), so the 22.04 build runs; the 24.04
# build wants 2.39 and does not.
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm
ARG ADDON_VERSION=dev
FROM ${BUILD_FROM}

ARG ADDON_VERSION
ENV ADDON_VERSION=${ADDON_VERSION} \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    BAMBU_HOME=/opt/bruh-bambu \
    BAMBU_DATA=/data

# Three groups of packages.
#
# The screen: Xvfb is the display Bambu Studio draws on, openbox keeps its
# windows maximised and movable, x11vnc reads the screen, and noVNC is the
# browser half the panel serves. There is no websockify — the panel bridges
# noVNC's websocket to x11vnc itself (panel/vnc_bridge.py), one process
# fewer and one port fewer.
#
# Bambu Studio's runtime: the AppImage carries most of its libraries and
# leaves GTK, WebKit, GStreamer and OpenGL to the system. Mesa's software
# renderer is the OpenGL here — there is no GPU in a container — which is
# slow for a big model's preview and perfectly fine for slicing.
#
# The panel: aiohttp for the routes, paho-mqtt for the printers' own MQTT
# (port 8883, TLS), PyYAML for config.yaml.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl jq file xz-utils squashfs-tools \
      xvfb x11vnc openbox x11-utils x11-xserver-utils xdotool dbus-x11 \
      novnc \
      libgtk-3-0 libwebkit2gtk-4.0-37 libsecret-1-0 libnotify4 \
      libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 \
      gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav \
      libegl1 libgl1 libgl1-mesa-dri libglu1-mesa libosmesa6 libglx-mesa0 \
      libudev1 libcurl4 libssl3 libfuse2 \
      fonts-dejavu-core fonts-liberation2 \
      python3 python3-aiohttp python3-paho-mqtt python3-yaml python3-venv \
    && rm -rf /var/lib/apt/lists/*

# The CAD half of Design with brAIn, in its own virtualenv so OpenCascade's
# pinned libraries never meet the panel's. A design script is built by
# /opt/cad/bin/python in a process of its own (panel/design/runner.py).
RUN python3 -m venv /opt/cad \
    && /opt/cad/bin/pip install --no-cache-dir \
       cadquery==2.8.0 trimesh==5.1.1 networkx==3.7 lxml==6.1.3 \
    && /opt/cad/bin/python -c "import cadquery, trimesh"

# three.js for the Design tab's 3D view, pinned and fetched here so the
# panel works with no internet at runtime.
ARG THREE_VERSION=0.160.0
RUN mkdir -p /opt/bruh-bambu/vendor \
    && for f in build/three.module.min.js examples/jsm/controls/OrbitControls.js \
                examples/jsm/loaders/STLLoader.js; do \
         curl -fsSL "https://cdn.jsdelivr.net/npm/three@${THREE_VERSION}/${f}" \
           -o "/opt/bruh-bambu/vendor/$(basename "${f}")" || exit 1; \
       done

# The one user everything runs as. Nothing in this add-on opens a device or
# binds a privileged port, so the slicer, the X server and the panel all
# run unprivileged; run.sh only uses root to lay out /data first.
RUN groupadd -g 1000 bambu \
    && useradd -m -u 1000 -g bambu -s /bin/bash -d /data/home bambu

RUN mkdir -p /opt/bruh-bambu/panel /opt/bruh-bambu/integrations \
      /opt/bruh-bambu/custom_components /data

WORKDIR /opt/bruh-bambu

COPY run.sh /run.sh
COPY openbox-rc.xml /opt/bruh-bambu/openbox-rc.xml
COPY panel/ /opt/bruh-bambu/panel/
COPY cad/ /opt/bruh-bambu/cad/
COPY lovelace/ /opt/bruh-bambu/lovelace/
COPY integrations/ /opt/bruh-bambu/integrations/
COPY custom_components/ /opt/bruh-bambu/custom_components/
COPY config.yaml /opt/bruh-bambu/config.yaml

RUN chmod +x /run.sh \
    && find /opt/bruh-bambu -type f -name "*.py" -exec chmod +x {} \;

# s6-overlay is /init in the HA base image; overriding ENTRYPOINT would
# bypass it and break bashio.
CMD ["/run.sh"]
