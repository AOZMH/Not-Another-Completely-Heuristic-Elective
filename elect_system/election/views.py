from __future__ import with_statement  #: 2.5 only
import typing
from django.http.request import HttpRequest
from django.http.response import JsonResponse
from .models import Election
from user.models import User
from user.models import stuLock
from course.models import Course
from phase.models import Phase
from phase.views import isElectionOpen
from course.views import get_time_json
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime
from threading import Lock
import json
import time
import traceback
from django.utils import timezone
import logging
from elect_system.settings import ELE_TYPE, ERR_TYPE
import random
import threading


@csrf_exempt
def schedule(request: HttpRequest, uid: str = ''):
    if request.method == 'GET':
        if uid == '':
            uid = request.user.username
        if not request.user.is_authenticated or \
                ((not request.user.is_superuser) and request.user.username != uid):
            return JsonResponse({
                'success': False,
                'msg': ERR_TYPE.NOT_ALLOWED,
            })

        if request.user.is_superuser and uid == request.user.username:
            return JsonResponse({
                'success': False,
                'msg': 'Dean cannot get personal schedule',
            })

        elList = Election.getCourseOfStudent(uid)
        crsList = []
        for el in elList:
            electedNum, pendingNum = Election.getCourseElecionNum(el.crs.course_id)
            crDict = {
                "course_id": el.crs.course_id,
                "name": el.crs.name,
                "credit": el.crs.credit,
                "main_class": el.crs.main_class,
                "sub_class": el.crs.sub_class,
                "times": get_time_json(el.crs),
                "lecturer": el.crs.lecturer,
                "pos": el.crs.pos,
                "dept": el.crs.dept,
                "election": {
                    "status": el.status,
                    "willingpoint": el.willingpoint,
                    "elected_num": electedNum,
                    "capacity": el.crs.capacity,
                    "pending_num": pendingNum
                }
            }
            crsList.append(crDict)

        u = User.objects.get(username=request.user.username)

        # Should not reach here
        if u is None:
            logging.error("User is None")
            return JsonResponse({'success': False, 'msg': ERR_TYPE.USER_404})
        return JsonResponse({'success': True, 'curCredit': u.curCredit, 'data': crsList})
    else:
        return JsonResponse({'success': False, 'msg': ERR_TYPE.INVALID_METHOD})


def checkTime(stuId: str, crsId: str) -> bool:
    crs = Course.getCourseObj(crsId)

    times = crs.times.all()
    tt = [[0 for i in range(10)] for j in range(8)]
    for time in times:
        d = time.day
        p = time.period
        tt[d][p] = 1

    # All courses that are elected or pending
    epList = Election.getCourseOfStudent(stuId)
    for ce in epList:
        c = Course.getCourseObj(ce.crs.course_id)
        for time in c.times.all():
            d = time.day
            p = time.period
            if tt[d][p]:
                return False
    return True


@csrf_exempt
def elect(request: HttpRequest):
    if request.method != 'POST':
        logging.warn(ERR_TYPE.INVALID_METHOD)
        return JsonResponse({'success': False, 'msg': ERR_TYPE.INVALID_METHOD})
    if not isElectionOpen():
        logging.warn('Election request on closed phase')
        return JsonResponse({'success': False, 'msg': ERR_TYPE.PHASE_ERR})

    if not request.user.is_authenticated or request.user.is_superuser:
        logging.warn(ERR_TYPE.NOT_ALLOWED)
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
    typeId = reqData.get('type')
    courseId = reqData.get('course_id')
    wp = reqData.get('willingpoint')

    if wp is None:
        wp = 0
    elif type(wp) is int and wp < 0:
        return JsonResponse({'success': False, 'msg': ERR_TYPE.WP_ERR})

    try:
        typeId = int(typeId)
        courseId = str(courseId)
        if wp:
            wp = int(wp)
    except:
        traceback.print_exc()
        logging.warn('Param type error, type(typeId)={}, type(wp)={}, type(courseId)={}'.format(
            type(typeId), type(wp), type(courseId)))
        return JsonResponse({'success': False, 'msg': ERR_TYPE.PARAM_ERR})

    # aquire lock
    lck = stuLock.get(request.user.username)
    if lck is None:
        return JsonResponse({'success': False, 'msg': ERR_TYPE.UNKNOWN})

    with lck:
        elSet = Election.objects.filter(
            stu__username=request.user.username, crs=courseId)

        # Election (add a new course to pending list)
        if typeId == 0:
            if elSet.count() != 0:
                logging.error('Duplicate election: stu={}, crs={}, count={}'.format(
                    request.user.username, courseId, elSet.count()))
                return JsonResponse({'success': False, 'msg': ERR_TYPE.ELE_DUP})
            if not Course.isLegal(courseId):
                logging.error(
                    'courseId not legal: courseId={}'.format(courseId))
                return JsonResponse({'success': False, 'msg': ERR_TYPE.COURSE_404})

            # Wp check
            wpCnt = Election.getWpCnt(request.user.username)
            if wpCnt + wp > 99:
                logging.error(
                    'Fail to add wp {}, cur wp is {}'.format(wp, wpCnt))
                return JsonResponse({'success': False, 'msg': ERR_TYPE.WP_ERR})
            if not checkTime(request.user.username, courseId):
                logging.error('Time conflict')
                return JsonResponse({'success': False, 'msg': ERR_TYPE.TIME_CONF})

            # Credit check
            u = User.objects.get(username=request.user.username)
            c = Course.getCourseObj(crsId=courseId)

            # Should not reach here
            if u is None or c is None:
                logging.error("User or course is None")
                return JsonResponse({'success': False, 'msg': ERR_TYPE.PARAM_ERR})

            if u.curCredit + c.credit > u.creditLimit:
                logging.warn('creditLimit exceeded: {} + {} > {}'.format(
                    u.curCredit, c.credit, u.creditLimit))
                return JsonResponse({'success': False, 'msg': ERR_TYPE.CRED_ERR})

            el = Election(willingpoint=wp, crs=c, credit=c.credit,
                          stu=u, status=ELE_TYPE.PENDING)
            u.curCredit += c.credit
            u.save()
            el.save()
            return JsonResponse({'success': True})

        # Edit wp
        elif typeId == 1:
            if elSet.count() != 1:
                logging.error('This election does not exists: stu={}, crs={}'.format(
                    request.user.username, courseId))
                return JsonResponse({'success': False, 'msg': ERR_TYPE.ELE_404})
            el = elSet.get()

            wpCnt = Election.getWpCnt(request.user.username)
            if wpCnt - el.willingpoint + wp > 99:
                logging.error('Fail to add wp {}, cur wp is {}'.format(
                    wp - el.willingpoint, wpCnt))
                return JsonResponse({'success': False, 'msg': ERR_TYPE.WP_ERR})
            el.willingpoint = wp
            el.save()
            return JsonResponse({'success': True})

        # Quit pending
        elif typeId == 2:
            if elSet.count() != 1:
                logging.error('This election does not exists: '
                              'stu={}, crs={}'.format(request.user.username,
                                                      courseId))
                return JsonResponse({'success': False, 'msg': ERR_TYPE.ELE_404})
            el = elSet.get()
            if el.status != ELE_TYPE.PENDING:
                logging.error('This election is not pending, '
                              'stu={}, crs={}, op={}'.format(request.user.username,
                                                             courseId, typeId))
                return JsonResponse({'success': False, 'msg': ERR_TYPE.ELE_FAIL})

            el.stu.curCredit -= el.crs.credit
            el.stu.save()
            el.delete()
            return JsonResponse({'success': True})

        # Drop
        elif typeId == 3:
            if elSet.count() != 1:
                logging.error('This election does not exists: stu={}, crs={}'.format(
                    request.user.username, courseId))
                return JsonResponse({'success': False, 'msg': ERR_TYPE.ELE_404})
            el = elSet.get()
            if el.status != ELE_TYPE.ELECTED:
                logging.error('This election is not elected, '
                              'stu={}, crs={}, op={}'.format(request.user.username,
                                                             courseId, typeId))
                return JsonResponse({'success': False, 'msg': ERR_TYPE.ELE_FAIL})

            el.stu.curCredit -= el.crs.credit
            el.stu.save()
            el.delete()
            return JsonResponse({'success': True})

        else:
            logging.error('Invalid typeId({})'.format(typeId))
            return JsonResponse({"success": False, 'msg': ERR_TYPE.PARAM_ERR})


@DeprecationWarning
def random_select(wpList, num):
    base_wp = 10
    wpList = [x + base_wp for x in wpList]
    for o in range(num):
        k = random.randint(1, sum(wpList))
        s = 0
        for i, x in enumerate(wpList):
            if s < k and s + x >= k:
                wpList[i] = 0
                break
            s += x
    return [i for i, x in enumerate(wpList) if x == 0]


@DeprecationWarning
def random_elect():
    crsList = Course.objects.all()
    for crs in crsList:
        elList = Election.objects.filter(courseId=crs.course_id)
        capacity = crs.elect_num
        elect_num = elList.filter(status=ELE_TYPE.ELECTED)
        pending_num = elList.filter(status=ELE_TYPE.PENDING)

        # Student num not exceed, all successfully elected
        if elect_num + pending_num <= capacity:
            for el in elList:
                if el.status == ELE_TYPE.PENDING:
                    el.status = ELE_TYPE.ELECTED
                    el.save()
        # Ballot on this course
        else:
            elList = elList.filter(status=ELE_TYPE.PENDING)
            # All wp of pending elections on this course
            wpList = [el.willingpoint for el in elList]
            elected_stu = random_select(wpList, capacity - elect_num)
            index = 0
            for i, el in enumerate(elList):
                if index >= len(elected_stu):
                    el.delete()
                elif i == elected_stu[index]:
                    el.status = ELE_TYPE.ELECTED
                    el.save()
                    index += 1
                else:
                    el.delete()
    return True


class watcherThread(threading.Thread):
    def run(self):
        electionHasStarted = False
        while True:
            time.sleep(20)
            if not isElectionOpen():
                if not electionHasStarted:
                    logging.info('Election closed. Ballot begins!')
                    fairBallot()
                    electionHasStarted = True
                logging.info('Balloting (Election closed)')
            else:
                electionHasStarted = False
                logging.info('Election open...')

# NOTE: This line should be comment out when migrating or running unittest
# watcherThread().start()
