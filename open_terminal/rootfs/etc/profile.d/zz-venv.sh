# Python-Umgebung der App (Pakete aus den Optionen, per uv in ~/.venv) vor das System-Python.
# Im Mehrbenutzer-Modus nutzen weitere Konten die Umgebung von "user" (nur lesen).
_v="$HOME/.venv"
[ -d "$_v/bin" ] || _v=/home/user/.venv
if [ -r "$_v/bin/python" ]; then
  case ":$PATH:" in *":$_v/bin:"*) ;; *) PATH="$_v/bin:$PATH" ;; esac
  VIRTUAL_ENV="$_v"
  export PATH VIRTUAL_ENV
fi
unset _v
