#!/bin/bash

set -e

cd ~ || ex

sudo apt update
sudo apt remove mysql-server mysql-client
sudo apt install libcups2-dev redis-server mariadb-client libmariadb-dev

# Frappe source. Defaults to this fork's pinned `vectora` branch rather than
# upstream develop, which moves under us: two builds a week apart used to
# contain different framework code with no way to reproduce the earlier one.
FRAPPE_REPO="${FRAPPE_REPO:-https://github.com/Absolute-Insight/frappe}"
FRAPPE_BRANCH="${FRAPPE_BRANCH:-vectora}"
# erpnext is a separate project and has no `vectora` branch; it was sharing
# FRAPPE_BRANCH, so pinning frappe would have broken the erpnext lane.
ERPNEXT_BRANCH="${ERPNEXT_BRANCH:-develop}"

pip install frappe-bench
git clone "${FRAPPE_REPO}" --branch "${FRAPPE_BRANCH}" --depth 1
bench init --skip-assets --frappe-path ~/frappe --python "$(which python)" frappe-bench

mkdir ~/frappe-bench/sites/test_site

cp -r "${GITHUB_WORKSPACE}/.github/helper/site_config.json" ~/frappe-bench/sites/test_site/site_config.json

mariadb --host 127.0.0.1 --port 3306 -u root -proot -e "SET GLOBAL character_set_server = 'utf8mb4'"
mariadb --host 127.0.0.1 --port 3306 -u root -proot -e "SET GLOBAL collation_server = 'utf8mb4_unicode_ci'"

mariadb --host 127.0.0.1 --port 3306 -u root -proot -e "CREATE USER 'test_frappe'@'localhost' IDENTIFIED BY 'test_frappe'"
mariadb --host 127.0.0.1 --port 3306 -u root -proot -e "CREATE DATABASE test_frappe"
mariadb --host 127.0.0.1 --port 3306 -u root -proot -e "GRANT ALL PRIVILEGES ON \`test_frappe\`.* TO 'test_frappe'@'localhost'"

mariadb --host 127.0.0.1 --port 3306 -u root -proot -e "FLUSH PRIVILEGES"

install_whktml() {
    wget -O /tmp/wkhtmltox.tar.xz https://github.com/frappe/wkhtmltopdf/raw/master/wkhtmltox-0.12.3_linux-generic-amd64.tar.xz
    tar -xf /tmp/wkhtmltox.tar.xz -C /tmp
    sudo mv /tmp/wkhtmltox/bin/wkhtmltopdf /usr/local/bin/wkhtmltopdf
    sudo chmod o+x /usr/local/bin/wkhtmltopdf
}
install_whktml &

cd ~/frappe-bench || exit

sed -i 's/watch:/# watch:/g' Procfile
sed -i 's/schedule:/# schedule:/g' Procfile
sed -i 's/socketio:/# socketio:/g' Procfile
sed -i 's/redis_socketio:/# redis_socketio:/g' Procfile

bench get-app crm "${GITHUB_WORKSPACE}"

# Only pull erpnext when the integration is under test, to keep other runs fast.
if [ "${INSTALL_ERPNEXT}" = "true" ]; then
    bench get-app erpnext --branch "${ERPNEXT_BRANCH}"
fi

bench setup requirements --dev

bench start &>> ~/frappe-bench/bench_start.log &
CI=Yes bench build --app frappe &
bench --site test_site reinstall --yes

if [ "${INSTALL_ERPNEXT}" = "true" ]; then
    bench --verbose --site test_site install-app erpnext crm
else
    bench --verbose --site test_site install-app crm
fi