#!/bin/bash
cd /home/admin/monica-dashboard
git add -A
git commit -m "auto: $(date '+%Y-%m-%d %H:%M') $(hostname)" --allow-empty
git push origin main 2>&1 | tee -a /var/log/monica/git_push.log
