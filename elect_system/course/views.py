from election.models import Election
from course.models import DEPT
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse, HttpRequest
from django.http import response
from django.views.decorators.csrf import csrf_exempt
import json
import traceback
import logging
import django.contrib.auth as auth
from course.models import Course, Time
from elect_system.settings import ERR_TYPE


@csrf_exempt
def dept(request: HttpRequest):
    return JsonResponse({'success': True, 'data': DEPT})


@csrf_exempt
def show_all_course(request: HttpRequest):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'msg': 'Please login first', })
    if request.method != 'POST':
        return JsonResponse({'success': False, 'msg': 'Wrong method', })
    courseList = Course.objects.all()
    courseinfo_list = []
    for course in courseList:
        couserInfo = {
            "name": course.name,
            "detail": course.detail,
            "capacity": course.capacity,
            "elected": course.elect_num,
            "waiting_num": course.elect_newround_num
        }
        courseinfo_list.append(couserInfo)

    return JsonResponse({'success': True, 'msg': courseinfo_list, })


def check_time_format(time):
    ''' TODO
    [
        {"day":2, "period":[3,4]},
        {"day":4, "period":[5,6]},
    ]
    '''
    return True


def get_time_json(course: Course):
    times = course.times.all()
    json = {}
    for time in times:
        day = time.day
        period = time.period
        if json.get(day):
            json[day]["period"].append(period)
        else:
            json[day] = {
                "day": day,
                "period": [period]
            }
    return [x for x in json.values()]


def check_time(course, day, period):
    times = course.times.all()
    for time in times:
        if time.day == day and (time.period in period):
            return True
    return False


@csrf_exempt
def course(request: HttpRequest, crsIdInURL: str = ''):
    if request.method == 'POST':
        if not request.user.is_superuser:
            logging.warn('user create course without privilege')
            return JsonResponse({'success': False, 'msg': ERR_TYPE.NOT_ALLOWED})

        try:
            reqData = json.loads(request.body.decode())
        except:
            logging.error('Json format error, req.body={}'.format(
                request.body.decode()))
            traceback.print_exc()
            return JsonResponse({'success': False, 'msg': ERR_TYPE.JSON_ERR})

        crss = reqData.get('courses')
        if crss is None or type(crss) is not list:
            logging.warn('courses param err, req={}'.format(reqData))
            return JsonResponse({'success': False, 'msg': ERR_TYPE.PARAM_ERR})

        for crs in crss:
            courseId = crs.get('course_id')
            name = crs.get('name')
            credit = crs.get('credit')
            lecturer = crs.get('lecturer')
            pos = crs.get('pos')
            dept = crs.get('dept')
            detail = crs.get('detail')
            main_class = crs.get('main_class')
            sub_class = crs.get('sub_class')
            times = crs.get('times')
            capacity = crs.get('capacity')

            try:
                courseId = str(courseId)
                name = str(name)
                credit = int(credit)
                dept = int(dept)
                main_class = int(main_class)
                capacity = int(capacity)
            except:
                traceback.print_exc()
                logging.warn('Create course param type error, crs={}'.format(crs))
                return JsonResponse({'success': False, 'msg': ERR_TYPE.PARAM_ERR})

            if not isinstance(name, str) or \
                    not isinstance(lecturer, str) or \
                    not isinstance(pos, str) or \
                    not isinstance(detail, str) or \
                    not isinstance(times, list) or \
                    not isinstance(sub_class, str):
                logging.warn('course attr format err, crs={}'.format(crs))
                return JsonResponse({'success': False, 'msg': ERR_TYPE.PARAM_ERR})
            # TODO: time PARAM CHECK

            # course already exists
            if Course.objects.filter(course_id=courseId).exists():
                logging.warn(
                    'Cannot add for course already exist, crsId={}'.format(courseId))
                return JsonResponse({'success': False, 'msg': ERR_TYPE.COURSE_DUP})

            c = Course.objects.create(course_id=courseId, name=name, credit=credit,
                                      lecturer=lecturer, pos=pos, dept=dept,
                                      main_class=main_class, sub_class=sub_class,
                                      detail=detail, capacity=capacity)

            for tim in times:
                day = tim.get('day')
                period = tim.get('period')
                if not isinstance(day, int) or \
                        not isinstance(period, list):
                    logging.warn('Time field error, time={}'.format(times))
                    return JsonResponse({'success': False, 'msg': ERR_TYPE.PARAM_ERR})
                for per in period:
                    try:
                        t = Time.objects.create(course=c, day=day, period=per)
                        t.save()
                        c.times.add(t)
                    except:
                        traceback.print_exc()
                        logging.error('Unknown err 8086')
                        return JsonResponse({'success': False, 'msg': ERR_TYPE.UNKNOWN})
            try:
                c.save()
            except:
                traceback.print_exc()
                logging.error('Unknown err 8087')
                return JsonResponse({'success': False, 'msg': ERR_TYPE.UNKNOWN})

        return JsonResponse({'success': True})

    elif request.method == 'GET':
        # For queries of args not carried in URL, empty string will be returned
        crsId = request.GET.get('id')
        dept = request.GET.get('dept')
        period = request.GET.get('period')
        day = request.GET.get('day')
        name = request.GET.get('name')
        main_class = request.GET.get('main_class')
        sub_class = request.GET.get('sub_class')

        if crsIdInURL != '':
            crsId = crsIdInURL

        course_list = Course.objects.all()
        if crsId:
            course_list = course_list.filter(course_id=crsId)
        if dept:
            course_list = course_list.filter(dept=dept)
        if name:
            course_list = course_list.filter(name=name)
        if main_class:
            course_list = course_list.filter(main_class=main_class)
        if sub_class:
            course_list = course_list.filter(sub_class=sub_class)
        if day and period:
            day = int(day)
            period = [int(x) for x in period.split(',')]
            course_list = [
                x for x in course_list if check_time(x, day, period)]

        course_json_list = []
        for course in course_list:
            elected, pending = Election.getCourseElecionNum(course.course_id)
            st, wp = 0, 0
            if request.user.is_authenticated:
                st, wp = Election.getStuElectionNum(
                    request.user.username, course.course_id)
            course_json = {
                "course_id": course.course_id,
                "name": course.name,
                "credit": course.credit,
                "main_class": course.main_class,
                "sub_class": course.sub_class,
                "times": get_time_json(course),
                "lecturer": course.lecturer,
                "pos": course.pos,
                "dept": course.dept,
                "detail": course.detail,
                "election": {
                    "status": st,
                    "willingpoint": wp,
                    "elected_num": elected,
                    "capacity": course.capacity,
                    "pending_num": pending
                }
            }
            course_json_list.append(course_json)
        return JsonResponse({'success': True, 'course_list': course_json_list})

    elif request.method == 'DELETE':
        if not request.user.is_superuser:
            logging.warn('user delete course without privilege')
            return JsonResponse({'success': False, 'msg': ERR_TYPE.NOT_ALLOWED})
        crsSet = Course.objects.filter(course_id=crsIdInURL)
        crsSet.delete()
        return JsonResponse({'success': True})

    else:
        logging.warn('invalid method: {}'.format(request.method))
        return JsonResponse({'success': False, 'msg': ERR_TYPE.INVALID_METHOD})


@csrf_exempt
def courseinfo(request: HttpRequest, course_id: str = ''):
    if request.method == 'GET':
        try:
            course = Course.objects.get(course_id=course_id)

            def get_time_json(course):
                times = course.times.all()
                json = {}
                for time in times:
                    day = time.day
                    period = time.period
                    if json.get(day):
                        json[day]["period"].append(period)
                    else:
                        json[day] = {
                            "day": day,
                            "period": [period]
                        }
                return [x for x in json.values()]
            course_json = {
                "course_id": course.course_id,
                "name": course.name,
                "credit": course.credit,
                "main_class": course.main_class,
                "sub_class": course.sub_class,
                "times": get_time_json(course),
                "lecturer": course.lecturer,
                "pos": course.pos,
                "dept": course.dept,
                "detail": course.detail,
                "election": {
                    "status": 0,
                    "willingpoint": 99,
                    "elected_num": course.elect_num,
                    "capacity": course.capacity,
                    "pending_num": course.elect_newround_num
                }
            }
            return JsonResponse(course_json)
        except:
            return JsonResponse({'success': False, 'msg': ERR_TYPE.COURSE_404})
    else:
        JsonResponse({'success': False, 'msg': ERR_TYPE.INVALID_METHOD})
