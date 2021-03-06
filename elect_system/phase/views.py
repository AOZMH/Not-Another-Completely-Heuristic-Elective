import json
import traceback
import logging
from threading import Lock
from django.http.request import HttpRequest
from django.http.response import JsonResponse
from .models import Phase, electionOpen, sch
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime
from django.utils import timezone
from elect_system.settings import ERR_TYPE, ELE_TYPE
from election.models import Election
from user.models import User, Message
from course.models import Course
from django_apscheduler.jobstores import DjangoJobStore, register_events, register_job

sch.add_jobstore(DjangoJobStore(), 'default')
register_events(sch)
sch.start()


def isElectionOpen():
    return electionOpen


@csrf_exempt
def phases_new(request: HttpRequest, phid: str = ''):
    if request.method == 'GET':
        retList = []
        jobList = sch.get_jobs()
        for job in jobList:
            logging.info(job.id)
            jobDict = {
                'id': job.id,
                'theme': '抽签',
                'detail': '抽签通常在十分钟之内完成，抽签期间无法选课',
                'is_open': False,
                'start_time': job.trigger.run_date,
                'end_time': job.trigger.run_date,
            }
            retList.append(jobDict)
        return JsonResponse({'success': True, 'data': retList})

    elif request.method == 'POST':
        if not request.user.is_authenticated or not request.user.is_superuser:
            logging.warn('Unprivileged user try to create phase, uid={}'.format(
                request.user.username))
            return JsonResponse({
                'success': False,
                'msg': ERR_TYPE.NOT_ALLOWED,
            })

        try:
            reqData = json.loads(request.body.decode())
        except:
            traceback.print_exc()
            logging.error('Json format error, req.body={}'.format(
                request.body.decode()))
            return JsonResponse({'success': False, 'msg': ERR_TYPE.JSON_ERR})

        phs = reqData.get('phases')
        if not phs:
            logging.error('Create phase without phs')
            return JsonResponse({'success': False, 'msg': ERR_TYPE.PARAM_ERR})
        if not isinstance(phs, list):
            logging.error('phs is not list')
            return JsonResponse({'success': False, 'msg': ERR_TYPE.PARAM_ERR})

        # NOTE: the front end only support adding one phase per request,
        #       warn on multiple additions
        if len(phs) > 1:
            logging.error(ERR_TYPE.GT_ONE)
            return JsonResponse({'success': False, 'msg': ERR_TYPE.GT_ONE})

        # Only on element in list. Not a real loop
        for ph in phs:
            phTheme = ph.get('theme')
            phDetail = ph.get('detail')
            if phDetail is None:
                phDetail = ''
            phIsOpen = ph.get('is_open')
            phStartTime = ph.get('start_time')
            phEndTime = ph.get('end_time')

            try:
                phTheme = str(phTheme)
                phDetail = str(phDetail)
                phIsOpen = bool(phIsOpen)
                phStartTime = int(phStartTime)
                phEndTime = int(phEndTime)
            except:
                traceback.print_exc()
                logging.warn('Create phase param type error')
                return JsonResponse({'success': False, 'msg': ERR_TYPE.PARAM_ERR})

            if phTheme is None or phIsOpen is None or \
                    phStartTime is None or phEndTime is None:
                logging.warn('Missing required params')
                return JsonResponse({'success': False, 'msg': ERR_TYPE.PARAM_ERR})

            # Make system aware of current timezone (Copy from CSDN)
            startDateTime = timezone.make_aware(datetime.fromtimestamp(
                phStartTime/1000), timezone.get_current_timezone())

            # Cannot add job in the past
            if startDateTime < timezone.make_aware(datetime.now()):
                logging.error(ERR_TYPE.OUTDATED)
                return JsonResponse({'success': False, 'msg': ERR_TYPE.OUTDATED})

            newBallot = sch.add_job(
                fairBallot, trigger='date', run_date=startDateTime)

        return JsonResponse({'success': True})

    elif request.method == 'DELETE':
        if not request.user.is_authenticated or not request.user.is_superuser:
            logging.warn('Unprivileged user try to delete phase, uid={}'.format(
                request.user.username))
            return JsonResponse({
                'success': False,
                'msg': ERR_TYPE.NOT_ALLOWED,
            })
        logging.debug(phid)
        job = sch.get_job(phid)
        if job is not None:
            job.remove()
            logging.debug('Job {} removed'.format(phid))
        return JsonResponse({'success': True})
    else:
        return JsonResponse({'success': False, 'msg': 'Invalid method'})


def fetchWp(el: Election):
    return el.willingpoint


def courseFairBallot(elList: list, fetchNum: int):
    elList.sort(key=fetchWp, reverse=True)
    for i, el in enumerate(elList):
        # Succeeded
        if (i < fetchNum):
            el.status = ELE_TYPE.NEW_ELECTED
            el.save()
        # Failed
        else:
            el.stu.curCredit -= el.crs.credit
            el.status = ELE_TYPE.NEW_FAILED
            el.save()
            el.stu.save()


def pushMessage(uid: str):
    msgStr = '抽签结束，您成功选中的课程：'
    okSet = Election.objects.filter(stu__username=uid).filter(status=ELE_TYPE.NEW_ELECTED)
    idx = 0
    for el in okSet:
        if idx > 0:
            msgStr += '、'
        msgStr += (el.crs.name)
        el.status = ELE_TYPE.ELECTED
        el.save()
        idx += 1
    
    msgStr += '，未选中的课程：'
    failSet = Election.objects.filter(stu__username=uid).filter(status=ELE_TYPE.NEW_FAILED)
    idx = 0
    for el in failSet:
        if idx > 0:
            msgStr += '、'
        msgStr += (el.crs.name)
        el.delete()
        idx += 1
    msgStr += '。'
    
    if okSet.exists() or failSet.exists():
        uSet = User.objects.filter(username=uid)
        u = uSet.get()
        curTime = timezone.make_aware(datetime.now())
        msg = Message.objects.create(title='抽签结果', genTime=curTime, content=msgStr, hasRead=False)
        msg.save()
        u.messages.add(msg)
        u.save()


# Ballot fairly: willing point is the only factor that determine ballot result
def fairBallot():
    electionOpen = False
    for crs in Course.objects.all():
        electedNum = Election.objects.filter(
            crs=crs.course_id).filter(status=ELE_TYPE.ELECTED).count()
        pendingSet = Election.objects.filter(
            crs=crs.course_id).filter(status=ELE_TYPE.PENDING)
        capacityLeft = crs.capacity - electedNum
        logging.info('Balloting on course {}, cap={}, elected={}, pending={}'.format(crs.course_id,
                                                                                     crs.capacity, electedNum, pendingSet.count()))
        courseFairBallot(list(pendingSet), capacityLeft)
    for stu in User.objects.all():
        if stu.is_superuser:
            logging.error('Why dean appear in User table? uid={}'.format(stu.username))
        pushMessage(stu.username)

    electionOpen = True


"""
=========================================================================================
=========================== Functions below are deprecated ==============================
=========================================================================================
"""


@DeprecationWarning
def curPhase() -> Phase:
    now = timezone.now()
    ph = None
    phaseSet = Phase.objects.filter(startTime__lte=now)
    phaseSet = phaseSet.filter(endTime__gt=now)
    if phaseSet.count() == 0:
        # logging.warn('Not in any phases now')
        return None
    elif phaseSet.count() > 1:
        logging.error('Overlapping phases! count={}'.format(phaseSet.count()))
        return None
    else:
        ph = phaseSet.get()
    return ph


@DeprecationWarning
def isOpenNow() -> bool:
    cp = curPhase()
    if cp is None:
        return True
    return curPhase().isOpen


@DeprecationWarning
@csrf_exempt
def current(request: HttpRequest):
    ph = curPhase()
    phDict = {
        'id': ph.id,
        'theme': ph.theme,
        'detail': ph.detail,
        'is_open': ph.isOpen,
        'start_time': ph.startTime,
        'end_time': ph.endTime,
    }
    return JsonResponse({'success': True, 'data': phDict})


@DeprecationWarning
@csrf_exempt
def phases(request: HttpRequest, phid: str = ''):
    if request.method == 'GET':
        phList = []
        phSet = Phase.objects.filter()
        for idx in range(0, phSet.count()):
            ph = phSet[idx]
            phDict = {
                'id': ph.id,
                'theme': ph.theme,
                'detail': ph.detail,
                'is_open': ph.isOpen,
                'start_time': ph.startTime,
                'end_time': ph.endTime,
            }
            phList.append(phDict)
        return JsonResponse({'success': True, 'data': phList})

    elif request.method == 'POST':
        if not request.user.is_authenticated or not request.user.is_superuser:
            logging.warn('Unprivileged user try to create phase, uid={}'.format(
                request.user.username))
            return JsonResponse({
                'success': False,
                'msg': ERR_TYPE.NOT_ALLOWED,
            })

        try:
            reqData = json.loads(request.body.decode())
        except:
            traceback.print_exc()
            logging.error('Json format error, req.body={}'.format(
                request.body.decode()))
            return JsonResponse({'success': False, 'msg': ERR_TYPE.JSON_ERR})

        phs = reqData.get('phases')
        if not phs:
            logging.error('Create phase without phs')
            return JsonResponse({'success': False, 'msg': ERR_TYPE.PARAM_ERR})
        if not isinstance(phs, list):
            logging.error('phs is not list')
            return JsonResponse({'success': False, 'msg': ERR_TYPE.PARAM_ERR})

        phSet = Phase.objects.filter()

        # NOTE: the front end only support adding one phase per request,
        #       warn on multiple additions
        if len(phs) > 1:
            logging.error(ERR_TYPE.GT_ONE)
            return JsonResponse({'success': False, 'msg': ERR_TYPE.GT_ONE})

        # Only on element in list. Not a real loop
        for ph in phs:
            phTheme = ph.get('theme')
            phDetail = ph.get('detail')
            if phDetail is None:
                phDetail = ''
            phIsOpen = ph.get('is_open')
            phStartTime = ph.get('start_time')
            phEndTime = ph.get('end_time')

            try:
                phTheme = str(phTheme)
                phDetail = str(phDetail)
                phIsOpen = bool(phIsOpen)
                phStartTime = int(phStartTime)
                phEndTime = int(phEndTime)
            except:
                traceback.print_exc()
                logging.warn('Create phase param type error')
                return JsonResponse({'success': False, 'msg': ERR_TYPE.PARAM_ERR})

            if phTheme is None or phIsOpen is None or \
                    phStartTime is None or phEndTime is None:
                logging.warn('Missing required params')
                return JsonResponse({'success': False, 'msg': ERR_TYPE.PARAM_ERR})

            # Make system aware of current timezone (Copy from CSDN)
            startDateTime = timezone.make_aware(datetime.fromtimestamp(
                phStartTime/1000), timezone.get_current_timezone())
            endDateTime = timezone.make_aware(datetime.fromtimestamp(
                phEndTime/1000), timezone.get_current_timezone())

            p = Phase(theme=phTheme, isOpen=phIsOpen,  detail=phDetail,
                      startTime=startDateTime, endTime=endDateTime)
            for ph in phSet:
                if p.overlapWith(ph):
                    logging.error(ERR_TYPE.OVERLAP)
                    return JsonResponse({'success': False, 'msg': ERR_TYPE.OVERLAP})
            if p.inThisPhase():
                logging.error(ERR_TYPE.HOT_EDIT)
                return JsonResponse({'success': False, 'msg': ERR_TYPE.HOT_EDIT})

            p.save()
        return JsonResponse({'success': True})

    elif request.method == 'DELETE':
        if not request.user.is_authenticated or not request.user.is_superuser:
            logging.warn('Unprivileged user try to delete phase, uid={}'.format(
                request.user.username))
            return JsonResponse({
                'success': False,
                'msg': ERR_TYPE.NOT_ALLOWED,
            })
        phSet = Phase.objects.filter(id=phid)
        for ph in phSet:
            if ph.inThisPhase():
                logging.error(
                    'Cannot delete current phase!(id={})'.format(ph.id))
                continue
            ph.delete()
        return JsonResponse({'success': True})
    else:
        return JsonResponse({'success': False, 'msg': 'Invalid method'})
