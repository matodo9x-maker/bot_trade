#!/bin/bash
set -euo pipefail

bash ./vps_stop.sh
sleep 1
bash ./vps_start.sh
