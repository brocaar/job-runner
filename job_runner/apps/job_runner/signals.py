from job_runner.apps.job_runner import notifications


def post_run_create(sender, instance, raw, **kwargs):
    """
    Post action after creating a run instance.

    This will make sure the ``schedule_id`` field is set.

    """
    if not instance.schedule_id:
        instance.schedule_id = instance.id
        instance.save()


def post_run_update(sender, instance, created, raw, **kwargs):
    """
    Post action after saving a run instance.

    This will call the ``reschedule`` method after a successful object
    update, which will re-schedule the job if needed (incl. children).

    If the object update represents the returning of a run with error,
    it will call also ``send_error_notification`` method.

    """
    if created or raw:
        return

    job = instance.job

    if instance.return_dts:
        if instance.return_success is False:
            # the run failed
            notifications.run_failed(instance)
            job.fail_times += 1
            job.last_completed_schedule_id = instance.schedule_id

            # disable job when it failed more than x times
            if (job.disable_enqueue_after_fails and
                    job.fail_times > job.disable_enqueue_after_fails):
                job.enqueue_is_enabled = False

            job.save()

        # on purpose we are not using .count() since with that, the
        # .select_for_update() does not have any effect.
        unfinished_siblings = len(instance.get_siblings().filter(
            return_dts__isnull=True).select_for_update())

        if not unfinished_siblings:
            job.reschedule()

        if instance.return_success:
            # reset the fail count
            job.fail_times = 0
            job.last_completed_schedule_id = instance.schedule_id
            job.save()

        if (instance.return_success and instance.schedule_children
                and not unfinished_siblings):

            failed_siblings = instance.get_siblings().filter(
                return_success=False)

            if not failed_siblings.count():
                # the job completed successfully including it's siblings
                # and has children to schedule now
                for child in instance.job.children.all():
                    child.schedule()
