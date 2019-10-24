import crhelper
import psycopg2
import sys

logger = crhelper.log_config({"RequestId": "CONTAINER_INIT"})
logger.info('Logging configured')
# set global to track init failures
init_failed = False

try:
    logger.info("Container initialization completed")
except Exception as e:
    logger.error(e, exc_info=True)
    init_failed = e

def create(event,context):
    print (event)
    try:
        conn = psycopg2.connect(
                dbname=event["ResourceProperties"]["DbName"],
                user=event["ResourceProperties"]["Username"],
                password=event["ResourceProperties"]["Password"],
                host=event["ResourceProperties"]["Host"],
                )
    except:
        raise ConnectionError("Failed with error: ", sys.exc_info()[0])

    cur = conn.cursor()
    function_create="""
CREATE FUNCTION exec(text) returns text language plpgsql volatile AS $f$ BEGIN EXECUTE $1; RETURN $1; END; $f$;
"""
    function_executor="""
SELECT exec('ALTER TABLE ' || quote_ident(s.nspname) || '.' || quote_ident(s.relname) || ' OWNER TO rds_superuser;')
  FROM (
    SELECT nspname, relname
    FROM pg_class c JOIN pg_namespace n ON (c.relnamespace = n.oid)
    WHERE nspname in ('tiger','topology') AND
    relkind IN ('r','S','v') ORDER BY relkind = 'S')
s;
"""

    try:
        cur.execute("CREATE EXTENSION postgis;")
        cur.execute("CREATE EXTENSION fuzzystrmatch;")
        cur.execute("CREATE EXTENSION postgis_tiger_geocoder;")
        cur.execute("CREATE EXTENSION postgis_topology;")
        cur.execute("ALTER SCHEMA tiger OWNER TO rds_superuser;")
        cur.execute("ALTER SCHEMA tiger_data OWNER TO rds_superuser;")
        cur.execute("ALTER SCHEMA topology OWNER TO rds_superuser;")
        cur.execute(function_create)
        cur.execute(function_executor)
        conn.commit()
    except:
        raise Exception("Failed with error: ", sys.exc_info()[0])
    finally:
        cur.close()
        if conn is not None:
            conn.close()

    print("Successfully installed postgis extension")


def update(event, context):
    return

def delete(event, context):
    return

def lambda_handler(event, context):
    global logger
    logger = crhelper.log_config(event)
    return crhelper.cfn_handler(event, context, create, update, delete, logger, init_failed)
