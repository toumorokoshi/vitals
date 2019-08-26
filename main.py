"""
vitals is designed to help one get as much information as possible about a 
process that freezes the UI. It accomplishes this by:

1. starting the process under strace, so system calls can be observed
2. concurrently starting multiple other processes to observe things like
   IO, CPU, memory.
3. printing these results to stdout and to files, so they can be looked at later.
"""
import asyncio
import logging
import sys
from typing import List

# using a global to manage coroutines
RUNNING_TASKS = []
logging.basicConfig(format="[%(asctime)s]: %(message)s", level=logging.INFO)


async def main(args=sys.argv[1:]):
    # first start an strace
    main_process = await asyncio.create_subprocess_exec(
        "strace",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    running_tasks = []
    running_tasks.append(
        asyncio.create_task(start_periodic_teed_process("iostat")))
    running_tasks.append(
        asyncio.create_task(start_periodic_teed_process("free", "-m")))
    out, err = await main_process.communicate()
    logging.info(out.decode() + err.decode())
    for t in running_tasks:
        t.cancel()


async def start_teed_process(*args: List[str]):
    """
    start a teed proceses, print the results to stdout.
    """
    proc = await asyncio.create_subprocess_exec(*args,
                                                stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    await asyncio.gather(read_to_logger(proc.stdout),
                         read_to_logger(proc.stderr))


async def read_to_logger(stream: asyncio.StreamReader):
    """ log lines read in from this stream. 

    Return when EOF has been received.
    """
    contents = await stream.readline()
    while contents:
        logging.info(contents)
        contents = await (stream.readline())


async def start_periodic_teed_process(*args: List[str],
                                      period_seconds: int = 2):
    """ start a periodic teed process.

    In constrast to start_teed_process, a periodic teed process will re-execute periodically. 
    """
    while True:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE)
        out, _err = await proc.communicate()
        logging.info(out.decode())
        await asyncio.sleep(period_seconds)


if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        raise