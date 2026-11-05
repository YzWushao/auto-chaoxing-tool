"""Process pending work cards and verify them independently of media progress."""


def process_quiz_chapter(client, course, point):
    jobs, info = client.get_job_list(course, point)
    if info.get('notOpen'):
        return 'blocked'
    work = {}
    for job in jobs:
        if job.get('type') == 'workid':
            key = job.get('jobid') or job.get('mid')
            if not key:
                raise ValueError('题目任务缺少标识，无法安全执行')
            work[key] = job
    if not work:
        return 'skipped'
    for job in work.values():
        if client.study_work(course, job, info).is_failure():
            return 'failed'
    remaining, current = client.get_job_list(course, point)
    if not current or current.get('notOpen'):
        raise ValueError('无法核对题目任务完成状态')
    if any(job.get('type') == 'workid' for job in remaining):
        raise ValueError('题目仍未被平台确认完成，请检查是否仅保存答案、题库覆盖率或提交设置')
    return 'done'
