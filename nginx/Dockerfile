# nginx for Ballroom Stats Analyzer: answers on your subdomain, handles HTTPS, passes visitors to the app.
FROM nginx:1.27-alpine

COPY comp-history.conf.template /etc/nginx/templates/default.conf.template
COPY 05-clean-env.envsh 30-wait-for-cert.sh 40-reload-certs.sh /docker-entrypoint.d/

# Strip Windows line endings (in case a file was edited in Notepad) and make the scripts runnable
RUN sed -i 's/\r$//' /etc/nginx/templates/default.conf.template /docker-entrypoint.d/05-clean-env.envsh \
        /docker-entrypoint.d/30-wait-for-cert.sh /docker-entrypoint.d/40-reload-certs.sh \
 && chmod +x /docker-entrypoint.d/05-clean-env.envsh /docker-entrypoint.d/30-wait-for-cert.sh \
        /docker-entrypoint.d/40-reload-certs.sh \
 && rm -f /etc/nginx/conf.d/default.conf
