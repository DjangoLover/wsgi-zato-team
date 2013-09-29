Installing on Ubuntu 12.04 from scratch
=======================================

Prerequisites
-------------

  user$ sudo apt-get install redis-server
  user$ sudo apt-get install postgresql-9.1

Set up PostgreSQL
-----------------

  user$ sudo su - postgres
  postgres$ createuser --no-superuser --no-createdb --no-createrole zato1
  postgres$ createdb --owner=zato1 zato1
  postgres$ psql --dbname zato1 --command="ALTER ROLE zato1 WITH PASSWORD 'zato1'"
  postgres$ exit

Install Zato binaries
---------------------

  user$ mkdir -p ~/tmp/zato-inst
  user$ cd ~/tmp/zato-inst
  user$ curl -O https://zato.io/download/zato-1.1.tar.bz2
  user$ curl -O https://zato.io/hotfixes/hotfixman.sh && bash hotfixman.sh
  user$ ./install.sh

Create a quickstart environment
-------------------------------

  user$ rm -rf ~/tmp/qs-1/ && mkdir ~/tmp/qs-1 && cd ~/tmp/qs-1/ && \
    zato quickstart create ~/tmp/qs-1/ postgresql localhost 5432 zato1 zato1 \
    localhost 6379 --odb_password zato1 --verbose

Start the environment
---------------------

  user$ cd ~/tmp/qs-1
  user$ ./zato-qs-start

Create server objects
---------------------