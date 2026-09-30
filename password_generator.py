import string


import random


import psutil


import time


import logging


# Logging configuration


logging.basicConfig(level=logging.INFO)


logger = logging.getLogger(__name__)


class PasswordGenerator:
    def __init__(self):
        self.last_generation_time = 0

        self.last_cpu_usage = 0

        self.last_ram_usage = 0
    def generate_password(self, length=60, include_numbers=True, include_uppercase=True, 

                         include_lowercase=True, include_special=True):
        """Generate a secure password with the specified characteristics"""

        try:
            # Validate length

            if length > 10_000_000:
                raise ValueError("Maximum allowed length is 10 million characters.")
            # Build character set

            characters = ""

            if include_numbers:
                characters += string.digits
            if include_uppercase:
                characters += string.ascii_uppercase
            if include_lowercase:
                characters += string.ascii_lowercase
            if include_special:
                characters += string.punctuation
            if not characters:
                raise ValueError("Select at least one type of character.")
            # Measure start time

            start_time = time.time()

            # Password generation

            password = ''.join(random.SystemRandom().choice(characters) for _ in range(length))

            # Measure time and resources

            self.last_generation_time = time.time() - start_time

            self.last_cpu_usage = psutil.cpu_percent(interval=0.1)

            self.last_ram_usage = psutil.virtual_memory().percent

            # Logging

            logger.info(f'Time to generate password: {self.last_generation_time:.6f} seconds')

            logger.info(f'CPU usage: {self.last_cpu_usage}%')

            logger.info(f'RAM usage: {self.last_ram_usage}%')

            return {

                "password": password,

                "time": f"{self.last_generation_time:.6f} seconds",

                "cpu_usage": f"{self.last_cpu_usage}%",

                "ram_usage": f"{self.last_ram_usage}%"
            }
        except Exception as e:
            logger.error(f"Error generating password: {str(e)}")

            raise
    def get_generation_stats(self):
        """Return the statistics of the last generation"""

        return {

            "time": self.last_generation_time,

            "cpu_usage": self.last_cpu_usage,

            "ram_usage": self.last_ram_usage
        } 
