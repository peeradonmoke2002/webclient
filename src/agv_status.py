#!/usr/bin/env python3
import socket
import traceback
import psycopg2
import rospy, rosnode, rospkg
from std_msgs.msg import Int32
from threading import Timer
import signal
import sys
import time

# Database connection parameters
DB_NAME = rospy.get_param('/agv/database/DB_NAME')
DB_USER = rospy.get_param('/agv/database/DB_USER')
DB_PASSWORD = rospy.get_param('/agv/database/DB_PASSWORD')
DB_HOST = rospy.get_param('/agv/database/DB_HOST')
DB_PORT = rospy.get_param('/agv/database/DB_PORT')
################################
# robot name
AGV_NAME = rospy.get_param('/agv/robot_id')
################################

## Path file ##
rospack = rospkg.RosPack()
package_path = rospack.get_path('webclient')
mappath = package_path + '/Map/'
configpath = package_path + '/robot_config/'
defaultMap = configpath + 'defaultMap.yaml'
###########################

run_rosbridge_check = True
rosbridge_timer = None

def signal_handler(signal, frame):
    global run_rosbridge_check, rosbridge_timer
    rospy.logwarn("Received termination signal. Stopping the periodic check.")
    run_rosbridge_check = False
    if rosbridge_timer:
        rosbridge_timer.cancel()
    # Additional cleanup tasks
    send_data_to_postgresql_and_set_rosparam(robot_name, 'Out of Service')
    rospy.logwarn("agv_status_publisher_node stopped!")
    sys.exit(0)

def check_database_connection():
    try:
        # Attempt to establish a connection to the database
        with psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT) as connection:
            rospy.loginfo('Connected to the database successfully.')
            return True
    except psycopg2.OperationalError as e:
        rospy.logerr('Error connecting to the database: %s', str(e))
        return False
    
def check_rosbridge_node():
    try:
        # Check if there are any clients connected to Rosbridge
        rospy.sleep(3.5)
        all_nodes = rosnode.get_node_names()

        if '/rosbridge_websocket' not in all_nodes:
            rospy.logerr('Rosbridge node is not running.')
            return False
        else:
            rospy.loginfo('Rosbridge node is running.')
            return True

    except rospy.ROSException as e:
        rospy.logerr('Error checking Rosbridge node status: %s', str(e))
        return False

def check_rosbridge_periodically():
    global run_rosbridge_check, rosbridge_timer

    if not run_rosbridge_check:
        rospy.loginfo("Periodic check stopped.")
        return

    try:
        # Your periodic check logic here
        if rospy.is_shutdown():
            # If rospy is already shut down, stop the periodic check
            rospy.loginfo("ROS has been shut down. Stopping the periodic check.")
            run_rosbridge_check = False
            return

        if not check_rosbridge_node():
            # Do something if Rosbridge is not active
            rospy.logwarn("Rosbridge is not active.")
            # Optionally, take corrective actions or log additional information

        # Schedule the next check
        rosbridge_timer = Timer(5, check_rosbridge_periodically)
        rosbridge_timer.start()

    except Exception as e:
        # Handle any exception
        rospy.logerr(f"Exception received: {e}. Stopping the periodic check.")
        run_rosbridge_check = False
        if rosbridge_timer:
            rosbridge_timer.cancel()

def get_rosbridge_server_ip():
    try:
        # Use a temporary socket connection to get the local IP address
        temp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        temp_socket.connect(("8.8.8.8", 80))  # Use a known external address
        ip_address = temp_socket.getsockname()[0]
        temp_socket.close()
        return ip_address
    except Exception as e:
        rospy.logerr("Error getting Rosbridge server IP: %s", str(e))
        return None

def send_data_to_postgresql_and_set_rosparam(robot_name, is_active):
    connection = None  # Initialize the connection variable

    try:
        # Establish a connection to the PostgreSQL database
        with psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT) as connection:
            with connection.cursor() as cursor:
                # Check if the robot already exists in the table
                check_query = "SELECT * FROM robots_config WHERE name = %s;"
                cursor.execute(check_query, (robot_name,))
                existing_robot = cursor.fetchone()

                if existing_robot:
                    # Update the status if the robot exists
                    update_query = "UPDATE robots_config SET is_active = %s WHERE name = %s;"
                    cursor.execute(update_query, (is_active, robot_name))
                else:
                    # Insert data into the table if the robot doesn't exist
                    insert_query = "INSERT INTO robots_config (name, is_active) VALUES (%s, %s);"
                    cursor.execute(insert_query, (robot_name, is_active))

                # Commit the transaction
                connection.commit()

                rospy.loginfo("Data updated in PostgreSQL for robot: %s", robot_name)

                # Set ROS parameter 'agv_status'
                rospy.set_param('/agv_status', is_active)

                # Print all data in the table
                select_all_query = "SELECT * FROM robots_config;"
                cursor.execute(select_all_query)
                all_data = cursor.fetchall()
                rospy.loginfo("All data in the table:")
                for row in all_data:
                    rospy.loginfo(row)

    except psycopg2.Error as e:
        rospy.logerr("PostgreSQL Error: %s", e)
    except rospy.ROSException as e:
        rospy.logerr("ROS Exception: %s", e)
    except Exception as e:
        # Log the exception with a stack trace
        rospy.logerr("Unexpected Error: %s", traceback.format_exc())


if __name__ == '__main__':
    try:
        # Initialize ROS node
        rospy.init_node('agv_status_publisher_node', anonymous=True)
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        if not check_database_connection():
            rospy.logerr('Unable to connect to the database. Exiting...')
            rospy.signal_shutdown('Unable to connect to the database.')
            sys.exit(1)

        robot_name = AGV_NAME
        is_active = True
        rate = rospy.Rate(1 / 15.0)

        while not rospy.is_shutdown():
            if not check_rosbridge_node():
                rospy.logerr('Rosbridge node is not available. Sending data as "Unavailable".')
                send_data_to_postgresql_and_set_rosparam(robot_name, 'Unavailable')
            else:
                rospy.loginfo('agv_status_publisher_node is ready ...')
                send_data_to_postgresql_and_set_rosparam(robot_name, 'Available')
            
            # Get Rosbridge server IP and send it to the database
            rosbridge_server_ip = get_rosbridge_server_ip()
            # if rosbridge_server_ip:
                # rospy.logerr("Rosbridge server IP: %s", rosbridge_server_ip)
                # rospy.set_param('/rosbridge_server_ip', rosbridge_server_ip)
        

    except rospy.ROSInterruptException:
        # Handle ROS node shutdown
        send_data_to_postgresql_and_set_rosparam(robot_name, 'Out of Service')
        rospy.logwarn('agv_status_publisher_node stopped!')
    except Exception as e:
        # Log the exception with a stack trace
        rospy.logerr('Unexpected error: %s', traceback.format_exc())
        send_data_to_postgresql_and_set_rosparam(robot_name, 'Out of Service')
        rospy.logwarn('agv_status_publisher_node stopped! %s', e)