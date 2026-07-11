#!/usr/bin/env bash
# Generates a local Certificate Authority + a server certificate so the phone can
# reach the computer over HTTPS on your LAN (required for mic + PWA install).
# Run once (re-run if your computer's LAN IP changes). Then install certs/rootCA.pem
# on the phone: Settings > Security > Encryption & credentials > Install a certificate > CA certificate.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p certs

IP="${1:-$(hostname -I | awk '{print $1}')}"
echo "Using LAN IP: $IP"

# 1) Local CA — trust this on the phone, once.
if [ ! -f certs/rootCA.pem ]; then
  openssl genrsa -out certs/rootCA.key 2048
  openssl req -x509 -new -nodes -key certs/rootCA.key -sha256 -days 3650 \
    -subj "/CN=Beatbox Local CA" -out certs/rootCA.pem
  echo "Created new local CA (certs/rootCA.pem)."
else
  echo "Reusing existing CA (certs/rootCA.pem)."
fi

# 2) Server leaf cert valid for localhost + this LAN IP + beatbox.local
cat > certs/leaf.cnf <<EOF
[req]
distinguished_name = dn
prompt = no
[dn]
CN = Beatbox Sync
[v3]
subjectAltName = @alt
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
[alt]
DNS.1 = localhost
DNS.2 = beatbox.local
IP.1  = 127.0.0.1
IP.2  = $IP
EOF

openssl genrsa -out certs/server.key 2048
openssl req -new -key certs/server.key -out certs/server.csr -config certs/leaf.cnf
openssl x509 -req -in certs/server.csr -CA certs/rootCA.pem -CAkey certs/rootCA.key \
  -CAcreateserial -out certs/server.crt -days 825 -sha256 \
  -extfile certs/leaf.cnf -extensions v3
cat certs/server.crt certs/rootCA.pem > certs/fullchain.crt
rm -f certs/server.csr certs/leaf.cnf

echo
echo "Done."
echo "  Server cert : certs/server.crt (+ certs/fullchain.crt)"
echo "  Server key  : certs/server.key"
echo "  Phone CA    : certs/rootCA.pem  <-- install this on the phone once"
echo
echo "Open on the phone:  https://$IP:8443/Beatbox%20to%20MIDI.dc.html"
