#!/bin/bash
# Start the Nanoleaf control panel and open it in the browser.
cd "$(dirname "$0")" || exit 1

PORT="${NANOLEAF_UI_PORT:-8765}"

# Already running? Just open it.
if curl -s -m 2 -o /dev/null "http://127.0.0.1:$PORT/"; then
  echo "Already running at http://127.0.0.1:$PORT"
  open "http://127.0.0.1:$PORT"
  exit 0
fi

python3 nanoleaf_server.py &
SERVER_PID=$!

# Wait for it to answer before opening the browser.
for _ in $(seq 1 20); do
  if curl -s -m 1 -o /dev/null "http://127.0.0.1:$PORT/"; then
    open "http://127.0.0.1:$PORT"
    echo "Control panel: http://127.0.0.1:$PORT   (Ctrl-C to stop)"
    wait $SERVER_PID
    exit 0
  fi
  sleep 0.5
done

echo "Server did not start - run 'python3 nanoleaf_server.py' directly to see the error."
kill $SERVER_PID 2>/dev/null
exit 1
