from azure.data.tables import TableServiceClient
from azure.core.exceptions import ResourceNotFoundError
import os
import logging
import threading

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TableStorageManager:
    def __init__(self, connection_string: str, table_name: str):
        self.table_name = table_name
        self.table_service_client = TableServiceClient.from_connection_string(connection_string)
        self.reset_timers = {}
        logger.info(f"TableStorageManager initialized with table: {self.table_name}")

    def get_table_client(self):
        return self.table_service_client.get_table_client(table_name=self.table_name)

    def get_message_count(self, phone_number):
        table_client = self.get_table_client()
        try:
            entity = table_client.get_entity(row_key=phone_number, partition_key=phone_number)
            logger.info(f"Retrieved message count for {phone_number}: {entity['MessageCount']}")
            return entity['MessageCount']
        except ResourceNotFoundError:
            logger.info(f"No message count found for {phone_number}, returning 0")
            return 0
        except Exception as e:
            logger.error(f"Error retrieving message count for {phone_number}: {e}")
            raise

    def update_message_count(self, phone_number, count):
        table_client = self.get_table_client()
        entity = {
            'PartitionKey': phone_number,
            'RowKey': phone_number,
            'MessageCount': count
        }
        try:
            table_client.upsert_entity(entity=entity)
            logger.info(f"Updated message count for {phone_number}: {count}")
        except Exception as e:
            logger.error(f"Error updating message count for {phone_number}: {e}")
            raise

    def reset_message_count(self, phone_number):
        table_client = self.get_table_client()
        try:
            entity = table_client.get_entity(partition_key=phone_number, row_key=phone_number)
            entity['MessageCount'] = 0
            table_client.update_entity(entity)
            logger.info(f"Message count successfully reset for {phone_number}.")
            return True
        except Exception as e:
            logger.error(f"Failed to reset message count for {phone_number}: {e}", exc_info=True)
            return False

    def is_notification_sent(self, phone_number):
        table_client = self.get_table_client()
        try:
            entity = table_client.get_entity(partition_key=phone_number, row_key=phone_number)
            return entity.get('NotificationSent', False)
        except Exception as e:
            logger.error(f"Error checking notification status for {phone_number}: {e}", exc_info=True)
            return False

    def set_notification_sent(self, phone_number, sent=True):
        table_client = self.get_table_client()
        try:
            entity = table_client.get_entity(partition_key=phone_number, row_key=phone_number)
            entity['NotificationSent'] = sent
            table_client.update_entity(entity)
            logger.info(f"Notification sent status set to {sent} for {phone_number}.")

            # Manage the timer for resetting the notification
            if sent:
                if phone_number in self.reset_timers:
                    self.reset_timers[phone_number].cancel()
                self.reset_timers[phone_number] = threading.Timer(120, self.reset_notification_sent, [phone_number])
                self.reset_timers[phone_number].start()
            else:
                if phone_number in self.reset_timers:
                    self.reset_timers[phone_number].cancel()
                    del self.reset_timers[phone_number]

        except Exception as e:
            logger.error(f"Failed to set notification status for {phone_number}: {e}", exc_info=True)

    def reset_notification_sent(self, phone_number):
        logger.info(f"Automatically resetting notification status for {phone_number}")
        self.set_notification_sent(phone_number, sent=False)
