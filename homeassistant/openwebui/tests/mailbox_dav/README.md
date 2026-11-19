# Test mailbox_dav

Gegen einen lokalen Radicale-Server (CalDAV/CardDAV), keine echten Zugangsdaten.

```
python3 -m venv v && v/bin/pip install radicale aiohttp pydantic python-dateutil
mkdir -p rad && printf 'anna@example.org:geheim123\n' > rad/users
printf '[server]\nhosts = 127.0.0.1:5232\n[auth]\ntype = htpasswd\nhtpasswd_filename = rad/users\nhtpasswd_encryption = plain\n[storage]\nfilesystem_folder = rad/coll\n[rights]\ntype = owner_only\n' > rad/config
bash seed.sh && v/bin/python t_dav.py
```
