'''
Created on Mar 18, 2017

@author: Johannes K. Fichte
'''

import codecs
import os
import re
import sys
from base64 import b64encode

from benchmarktool.tools import escape

runsolver_re = {
    "wall": ("float", re.compile(r"^Real time \(s\): (?P<val>[0-9]+(\.[0-9]+)?)$"), lambda x: x),
    "memerror": ("string", re.compile(r"^Maximum VSize (?P<val>exceeded): sending SIGTERM then SIGKILL"), lambda x: x),
    "segfault": (
        "string", re.compile(r"^\s*Child\s*ended\s*because\s*it\s*received\s*signal\s*11\s*\((?P<val>SIGSEGV)\)\s*"),
        lambda x: x),
    "time": ("float", re.compile(r"^Real time \(s\): (?P<val>[0-9]+(\.[0-9]+)?)$"), lambda x: x),
    "memusage": (
        "float", re.compile(r"^maximum resident set size= (?P<val>[0-9]+(\.[0-9]+)?)$"), lambda x: round(x / 1024, 2)),
    "status": ("int", re.compile(r"Child status: (?P<val>[0-9]+)"), lambda x: x),
    "cumcpu_time": (
        "float", re.compile("Current children cumulated CPU time \(s\)\s(?P<val>[0-9]+(\.[0-9]+)?)$"), lambda x: x)
}

detkdecomp_re = {
    "time": ("float", re.compile(r"^Real time \(s\): (?P<val>[0-9]+(\.[0-9]+)?)$"), lambda x: x),
    "memerror": ("string", re.compile(r"^Maximum VSize (?P<val>exceeded): sending SIGTERM then SIGKILL"), lambda x: x),
    "parse_wall": ("float", re.compile(r"^Parsing input file done in (?P<val>[0-9]+(\.[0-9]+)) sec"), lambda x: x),
    "hgbuild_wall": (
    "float", re.compile(r"^Building\s*hypergraph\s*done\s*in\s*(?P<val>[0-9]+(\.[0-9]+)*)\s*sec."), lambda x: x),
    "solve_wall": (
        "float", re.compile(r"Building hypertree done in (?P<val>[0-9]+(\.[0-9]+)*) sec \(hypertree-width: [0-9]+\)."),
        lambda x: x),
    "verify_wall": (
    "float", re.compile(r"^Checking hypertree conditions done in (?P<val>[0-9]+(\.[0-9]+)*) sec."), lambda x: x),
    "num_variables": (
        "int", re.compile(
            r"^Parsing\s*input\s*file\s*done\s*in\s*[0-9]+(\.[0-9]+)*\s*sec\s*\(([0-9]+)\s*atoms,\s*(?P<val>[0-9]+)\s*variables\)."),
        lambda x: x),
    "num_hyperedges": (
        "int", re.compile(
            r"^Parsing\s*input\s*file\s*done\s*in\s*[0-9]+(\.[0-9]+)*\s*sec\s*\((?P<val>[0-9]+)\s*atoms,\s*([0-9]+)\s*variables\)."),
        lambda x: x),
    "objective": (
        "float", re.compile(r"Building hypertree done in [0-9]+(\.[0-9]+)* sec \(hypertree-width: (?P<val>[0-9]+)\)."),
        lambda x: x),
    "cond1": ("string", re.compile(r"^Condition 1: (?P<val>satisfied)."), lambda x: x),
    "cond2": ("string", re.compile(r"^Condition 2: (?P<val>satisfied)."), lambda x: x),
    "cond3": ("string", re.compile(r"^Condition 3: (?P<val>satisfied)."), lambda x: x),
    "cond4": ("string", re.compile(r"^Condition 4: (?P<val>satisfied)."), lambda x: x)
}


def detkdecomp(root, runspec, instance):
    """
    Extracts some clingo statistics.
    """

    # DEFAULT VALUES
    res = {
        'instance': ('string', instance.instance),
        'setting': ('string', runspec.setting.name),
        'timelimit': ('int', runspec.project.job.timeout),
        'memlimit': ('int', runspec.project.job.memout),
        'memerror': ('string', 'nan'),
        'timeout': ('int', -1),
        'memout': ('int', -1),
        'solver': ('string', runspec.system.name),
        'solver_version': ('string', runspec.system.version),  # TODO:
        'solver_args': ('string', escape(runspec.setting.cmdline)),
        'full_call': ('string', None),
        'full_path': ('string', root),
        'hash': ('string', None),  # TODO:
        'solved': ('int', 0),
        'wall': ('float', 0),
        'run': ('int', 0),
        'objective': ('float', 'nan'),
        'error': ('int', 0),
        'error_str': ('string', ''),
        'stderr': ('string', ''),
        'status': ('int', -1)
    }

    # boxing = lambda x: (type(x).__name__, x)
    # rval = lambda x: x[1]

    pbs_job = 'PbsJob' in repr(runspec.project.job)
    instance_str = instance.instance
    valid_solver_run = True
    signal_handling_error = False
    invalid_result = False
    cplex_license_issue = False
    grounding_error = False

    # ERROR HANDLING
    try:
        logfile = os.path.join(root, '%s.err' % instance_str)
        err_content = codecs.open(logfile, errors='ignore', encoding='utf-8').read()
        err_content = err_content.replace(",\n]", "\n]", 1)

        if 'MemoryError: std::bad_alloc' in err_content:
            res['memout'] = ('int', 1)
            grounding_error = True

    except IOError:
        sys.stderr.write('Missing Error file for instance %s.\n' % root)

    # full call
    # runsolver
    # command line: ../../../../../../../../programs/runsolver-3.3.6 -M 8192 -W 7200 -w ../../../../../../../../output/fhtd-hypergraphs/behemoth/results/hyperbench-csp_other/fhtd-0.7-default-n1/./2bitcomp_5.hg/run1/2bitcomp_5.hg.watcher ../../../../../../../../programs/fhtd-0.\
    # 7 -t /tmp/3258669.1.all.q --runid 1 -f ../../../../../../../../benchmarks/hypergraphs/hyperbench/csp_other/2bitcomp_5.hg

    runsolver_error = False
    # WATCHER DATA HANDLING
    if pbs_job:
        try:
            filename = os.path.join(root, '%s.watcher' % instance_str)
            # print filename
            f = codecs.open(filename, errors='ignore', encoding='utf-8').read()
            for line in f.splitlines():
                for val, reg in runsolver_re.items():
                    m = reg[1].match(line)
                    if m: res[val] = (reg[0], reg[2](float(m.group("val"))) if reg[0] == "float" else m.group("val"))

            if res['memerror'][1] != 'nan':
                res["error_str"] = ("string", "std::bad_alloc")
                res["error"] = ("int", 2)
                res['memout'] = ("int", 1)
            else:
                res['memout'] = ("int", 0)

            try:
                res['timeout'] = ('int', int(res["time"][1] >= res['timelimit'][1]))
                if 'cumcpu_time' in res:
                    del res['cumcpu_time']
            except KeyError, e:
                # sometimes we obtain lost times during runs
                # we report them here but note that there was a runsolver error
                res['time'] = res['cumcpu_time']
                res['timeout'] = ('int', int(res["time"][1] >= res['timelimit']))
                runsolver_error = True

            res['finished'] = ('int', int(res['status'][1] >= 0))
            # to = log_content.find('Child ended because it received signal 15 (SIGTERM)') >=0
            if not res['finished']:
                sys.stderr.write('instance %s did not finish properly\n' % root)
        except IOError:
            res['error_str'] = ('string', 'Did not finish.')
            return [(key, val[0], val[1]) for key, val in res.items()]

    else:
        log_content = open(os.path.join(root, "condor.log")).read()
        # ret = 9: runsolver error (heavy process)
        finished = log_content.find('Normal termination') >= 0 or log_content.find(
            'Abnormal termination (signal 9)') >= 0
        if not finished:
            sys.stderr.write('instance %s did not finish properly\n' % root)

    # READ RESULT OUTPUT FROM SOLVER
    valid_json = None
    stats = {}
    error = 0
    cluster_error = False

    try:
        # errors='ignore',
        content = codecs.open(os.path.join(root, '%s.txt' % instance_str), encoding='utf-8').read()
        for line in content.splitlines():
            # print line
            for val, reg in detkdecomp_re.items():
                m = reg[1].match(line)
                if m: res[val] = (reg[0], reg[2](float(m.group("val"))) if reg[0] == "float" else m.group("val"))

        try:
            if res['cond1'] == res['cond2'] == res['cond3'] == res['cond4'] and res['objective']:
                res['solved'] = ('int', 1)
        except KeyError:
            res['solved'] = ('int', 0)
            invalid_result = True

    except IOError:
        sys.stderr.write('Instance %s did not finish properly. Missing output file.\n' % root)
        cluster_error = True

    # error codes: 0 = ok, 1 = timeout, 2 = memout, 64 = invalid output, 128 = program runtime error,
    # 256 = runsolver error/glitch, 512 = error signal handling, 1024 = cluster run error
    # 2048 = invalid result, 4096 = cplex license issue
    error += int(res['timeout'][1])
    error += int(res['memout'][1]) * 2
    error += int(not valid_solver_run) * 128
    error += int(runsolver_error) * 256
    # error += int(signal_handling_error) * 512
    error += int(cluster_error) * 1024
    error += int(invalid_result) * 2048
    # error += int(cplex_license_issue) * 4096
    # error += int(grounding_error) * 8192
    res['error'] = ('int', error)

    try:
        res['wall'] = ('float', stats['wall'])
    except KeyError, e:
        pass

    # PROBLEM/SOLVER SPECIFIC OUTPUT
    # if error == 0:
    #     try:
    #         res['run'] = ('int', stats['run'])
    #         res['hash'] = ('string', stats['hash'][0:16] + '*')
    #
    #         cut = os.path.join(*instance.location.split('/')[1:])
    #         index = stats['instance'].find(cut)
    #         if index != -1:
    #             res['instance_path'] = ('string', stats['instance'][index + len(cut) + 1:])
    #     except KeyError, e:
    #         sys.stderr.write('Missing attribute "%s" for instance "%s".\n' % (str(e), root))
    #     try:
    #         res['full_call'] = ('string', b64encode(stats['call']))
    #     except KeyError:
    #         res['full_call'] = ('string', 'nan')

    return [(key, val[0], val[1]) for key, val in res.items()]
