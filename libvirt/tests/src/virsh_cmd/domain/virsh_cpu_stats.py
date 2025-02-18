import re
import os.path
import logging

from avocado.utils import cpu

from virttest import virsh
from virttest.staging import utils_cgroup


def run(test, params, env):
    """
    Test virsh cpu-stats command.

    The command can display domain per-CPU and total statistics.
    1. Call virsh cpu-stats [domain]
    2. Call virsh cpu-stats [domain] with valid options
    3. Call virsh cpu-stats [domain] with invalid options
    """

    if not virsh.has_help_command('cpu-stats'):
        test.cancel("This version of libvirt does not support "
                    "the cpu-stats test")

    vm_name = params.get("main_vm", "vm1")
    vm_ref = params.get("cpu_stats_vm_ref")
    status_error = params.get("status_error", "no")
    options = params.get("cpu_stats_options")
    error_msg = params.get("error_msg", "")
    logging.debug("options are %s", options)

    if vm_ref == "name":
        vm_ref = vm_name

    # get host cpus num
    cpus = cpu.online_cpus_count()
    logging.debug("host online cpu num is %s", cpus)

    # get options and put into a dict
    get_total = re.search('total', options)
    get_start = re.search('start', options)
    get_count = re.search('count', options)

    # command without options
    get_noopt = 0
    if not get_total and not get_start and not get_count:
        get_noopt = 1

    # command with only --total option
    get_totalonly = 0
    if not get_start and not get_count and get_total:
        get_totalonly = 1

    option_dict = {}
    if options.strip():
        option_list = options.split('--')
        logging.debug("option_list is %s", option_list)
        for match in option_list[1:]:
            if get_start or get_count:
                option_dict[match.split(' ')[0]] = match.split(' ')[1]

    # check if cpu is enough,if not cancel the test
    if (status_error == "no"):
        cpu_start = int(option_dict.get("start", "0"))
        if cpu_start == 32:
            cpus = cpu.total_cpus_count()
            logging.debug("Host total cpu num: %s", cpus)
        if (cpu_start >= cpus):
            test.cancel("Host cpus are not enough")

    # Run virsh command
    cmd_result = virsh.cpu_stats(vm_ref, options,
                                 ignore_status=True, debug=True)
    output = cmd_result.stdout.strip()
    status = cmd_result.exit_status

    # check status_error
    if status_error == "yes":
        if status == 0:
            test.fail("Run successfully with wrong command! Output: {}"
                      .format(output))
        else:
            # Check error message is expected
            if not re.search(error_msg, cmd_result.stderr.strip()):
                test.fail("Error message is not expected! "
                          "Expected: {} Actual: {}"
                          .format(error_msg, cmd_result.stderr.strip()))
    elif status_error == "no":
        if status != 0:
            test.fail("Run failed with right command! Error: {}"
                      .format(cmd_result.stderr.strip()))
        else:
            # Get cgroup cpu_time
            if not get_totalonly:
                vm = env.get_vm(vm_ref)
                cgpath = utils_cgroup.resolve_task_cgroup_path(
                    vm.get_pid(), "cpuacct")
                # When a VM has an 'emulator' child cgroup present, we must
                # strip off that suffix when detecting the cgroup for a machine
                if os.path.basename(cgpath) == "emulator":
                    cgpath = os.path.dirname(cgpath)
                usage_file = os.path.join(cgpath, "cpuacct.usage_percpu")
                with open(usage_file, 'r') as f:
                    cgtime = f.read().strip().split()
                logging.debug("cgtime get is %s", cgtime)

            # Cut CPUs from output and format to list
            output = re.sub(r'\.', '', output)
            if get_total:
                mt_start = re.search('Total', output).start()
            else:
                mt_start = len(output)
            output_cpus = " ".join(output[:mt_start].split())
            cpus_list = re.compile(r'CPU\d+:').split(output_cpus)

            # conditions that list total time info
            if get_noopt or get_total:
                mt_end = re.search('Total', output).end()
                total_list = output[mt_end + 1:].split()

                total_time = int(total_list[1])
                user_time = int(total_list[4])
                system_time = int(total_list[7])

                # check Total cpu_time >= User + System cpu_time
                if user_time + system_time > total_time:
                    test.fail("total cpu_time < user_time + "
                              "system_time")
                logging.debug("Check total cpu_time %d >= user + system "
                              "cpu_time %d",
                              total_time, user_time + system_time)

            start_num = 0
            if get_start:
                start_num = int(option_dict["start"])

            end_num = int(cpus)
            if get_count:
                count_num = int(option_dict["count"])
                if end_num > start_num + count_num:
                    end_num = start_num + count_num

            # for only give --total option it only shows "Total" cpu info
            if get_totalonly:
                end_num = -1

            # find CPU[N] in output and sum the cpu_time and cgroup cpu_time
            sum_cputime = 0
            sum_cgtime = 0
            logging.debug("start_num %d, end_num %d", start_num, end_num)
            for i in range(start_num, end_num):
                if not re.search('CPU' + "%i" % i, output):
                    test.fail("Fail to find CPU" + "%i" % i + "in "
                              "result")
                logging.debug("Check CPU" + "%i" % i + " exist")
                sum_cputime += int(cpus_list[i - start_num + 1].split()[1])
                sum_cgtime += int(cgtime[i])

            # check cgroup cpu_time > sum of cpu_time
            if end_num >= 0:
                if sum_cputime > sum_cgtime:
                    test.fail("Check sum of cgroup cpu_time < sum "
                              "of output cpu_time")
                logging.debug("Check sum of cgroup cpu_time %d >= cpu_time %d",
                              sum_cgtime, sum_cputime)

            # check Total cpu_time >= sum of cpu_time when no options
            if get_noopt:
                if total_time < sum_cputime:
                    test.fail("total time < sum of output cpu_time")
                logging.debug("Check total time %d >= sum of output cpu_time"
                              " %d", total_time, sum_cputime)
