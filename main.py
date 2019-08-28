"""
vitals is designed to help one get as much information as possible about a 
process that freezes the UI. It accomplishes this by:

1. starting the process under strace, so system calls can be observed
2. concurrently starting multiple other processes to observe things like
   IO, CPU, memory.
3. printing these results to stdout and to files, so they can be looked at later.
"""
import asyncio
import datetime
import logging
import os
import sys
import tempfile
from typing import List, Optional

# using a global to manage coroutines
RUNNING_TASKS = []
logging.basicConfig(format="[%(asctime)s][%(name)s]: %(message)s",
                    level=logging.INFO)


class Output:
    """Handles writing strings out to stdout and files.

    There is value in vitals to differentiate between which incoming
    stream is writing output. The output class handles selecting the 
    appropriate stream to write to, as well as writing it to both
    stdout and to a file.
    """
    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = output_dir
        self._file_handle_cache = {}

    def write(self, stream_name: str, contents: str):
        if self.output_dir:
            if stream_name not in self._file_handle_cache:
                self._file_handle_cache[stream_name] = open(
                    os.path.join(self.output_dir, stream_name + ".txt"), "w+")
            now = datetime.datetime.now().isoformat()
            self._file_handle_cache[stream_name].write(f"[{now}]: {contents}")
        logging.getLogger(stream_name).info(contents.rstrip("\n"))

    async def read_stream(self, stream_name: str,
                          stream: asyncio.StreamReader):
        """ log lines read in from this stream. 

        Args:
            command_name: the name of the command run. This helps the logger identify where
                the message came from.

        Return when EOF has been received.
        """
        contents = await stream.readline()
        while contents:
            self.write(stream_name, contents.decode())
            contents = await (stream.readline())

    def __del__(self):
        for file_handle in self._file_handle_cache.values():
            file_handle.close()


async def main(args=sys.argv[1:]):
    # first start an strace
    # persistent directory to store logs per output, for diagnostics later
    output = Output(tempfile.mkdtemp())
    main_process = await asyncio.create_subprocess_exec(
        "strace",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    running_tasks = []
    running_tasks.append(
        asyncio.create_task(
            start_periodic_teed_process("iostat", output=output)))
    running_tasks.append(
        asyncio.create_task(
            start_periodic_teed_process("free", "-m", output=output)))
    await asyncio.gather(
        output.read_stream("main", main_process.stdout),
        output.read_stream("main", main_process.stderr),
    )
    for t in running_tasks:
        t.cancel()
    print(f"output written to {output.output_dir}")


async def start_teed_process(*args: List[str]):
    """
    start a teed proceses, print the results to stdout.
    """
    command = args[0]
    proc = await asyncio.create_subprocess_exec(*args,
                                                stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    await asyncio.gather(read_to_logger(command, proc.stdout),
                         read_to_logger(command, proc.stderr))


async def read_to_logger(command_name: str, stream: asyncio.StreamReader):
    """ log lines read in from this stream. 

    Args:
        command_name: the name of the command run. This helps the logger identify where
            the message came from.

    Return when EOF has been received.
    """
    logger = logging.getLogger(command_name)
    contents = await stream.readline()
    while contents:
        logger.info(contents)
        contents = await (stream.readline())


async def start_periodic_teed_process(*args: List[str],
                                      period_seconds: int = 2,
                                      output: Output = None):
    """ start a periodic teed process.

    In contrast to start_teed_process, a periodic teed process will re-execute periodically. 
    """
    stream_name = args[0]
    while True:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE)
        out, _err = await proc.communicate()
        output.write(stream_name, out.decode())
        await asyncio.sleep(period_seconds)


if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        raise
