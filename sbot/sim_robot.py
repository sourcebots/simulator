import time
from math import pi, sin, cos, degrees, hypot, atan2, radians

import math

from .game_object import GameObject
from .vision import Marker, PolarCoord
from .game_specific import MARKER_SIZES, WALL, TOKEN

import pypybox2d

SPEED_SCALE_FACTOR = 0.02
MAX_MOTOR_SPEED = 1

GRAB_RADIUS = 0.6
HALF_GRAB_SECTOR_WIDTH = pi / 4
HALF_FOV_WIDTH = pi / 6

GRABBER_OFFSET = 0.25
SPEED_OF_SOUND = 346

class AlreadyHoldingSomethingException(Exception):
    def __str__(self):
        return "The robot is already holding something."

BRAKE = 0  # 0 so setting the motors to 0 has exactly the same effect as setting the motors to BRAKE
COAST = 0.00000001

class MotorList(object):

    def __init__(self, robot):
        self._robot = robot
        self._motors = [0,0]

    def __setitem__(self, index, value):
        value = min(max(value, -MAX_MOTOR_SPEED), MAX_MOTOR_SPEED)
        with self._robot.lock:
            self._motors[index] = value

    def __getitem__(self, index):
        return self._motors[index]


class MotorBoard(object):
    VOLTAGE_SCALE = 1

    def __init__(self, robot):
        self.robot = robot
        self._motors = MotorList(robot)

    def _check_voltage(self,new_voltage):
        if new_voltage != COAST and (new_voltage > 1 or new_voltage < -1):
            raise ValueError(
                'Incorrect voltage value, valid values: between -1 and 1, robot.COAST, or robot.BRAKE')

    @property
    def motors(self):
        return self._motors

class UltrasoundSensorList(object):
    def __init__(self, robot):
        self._robot = robot

    def __getitem__(self, tup):
        trigger, echo = tup
        return UltrasoundSensor(self._robot, trigger, echo)

class UltrasoundSensor(object):

    ULTRASOUND_ANGLES = {
        (6, 7): ('ahead', 0),
        (8, 9): ('right', math.pi / 2),
        (10, 11): ('left', -math.pi / 2),
    }

    def __init__(self, robot, trigger_pin, echo_pin):
        self.robot = robot
        self.trigger_pin = trigger_pin
        self.echo_pin = echo_pin

    def distance(self):
        return self._read_ultrasound()

    def pulse(self):
        return self._read_ultrasound() / SPEED_OF_SOUND

    def _read_ultrasound(self):
        pin_pair = (self.trigger_pin, self.echo_pin)

        try:
            _, angle_offset = self.ULTRASOUND_ANGLES[pin_pair]
        except KeyError:
            print("There's no ultrasound module on those pins in the simulator. Try:")
            for (
                    (trigger_pin, echo_pin),
                    (direction, _),
            ) in self.ULTRASOUND_ANGLES.items():
                print("Pins {} and {} for the sensor pointing {}".format(
                    trigger_pin,
                    echo_pin,
                    direction,
                ))
            return 0.0

        result = self.robot._send_ultrasound_ping(angle_offset)

        if result is None:
            # No detection is equivalent to just not getting an echo response
            result = 0.0

        return result

class Arduino:
    def __init__(self, robot):
        self.robot = robot
        self._ultrasound_sensors = UltrasoundSensorList(robot)

    @property
    def ultrasound_sensors(self):
        return self._ultrasound_sensors

class Camera:
    def __init__(self, robot):
        self.robot = robot

    def see(self):
        with self.robot.lock:
            x, y = self.robot.location
            heading = self.robot.heading

        acq_time = time.time()
        # Block for a realistic amount of time
        time.sleep(0.2)

        MOTION_BLUR_SPEED_THRESHOLD = 5

        def robot_moving(robot):
            vx, vy = robot._body.linear_velocity
            return hypot(vx, vy) > MOTION_BLUR_SPEED_THRESHOLD

        def motion_blurred(o):
            # Simple approximation: we can't see anything if either it's moving
            # or we're moving. This doesn't handle tokens grabbed by other robots
            # but Sod's Law says we're likely to see those anyway.
            return (robot_moving(self.robot) or
                    isinstance(o, SimRobot) and robot_moving(o))

        def object_filter(o):
            # Choose only marked objects within the field of view
            direction = atan2(o.location[1] - y, o.location[0] - x)
            return (o.marker_id is not None and
                    o is not self and
                    -HALF_FOV_WIDTH < direction - heading < HALF_FOV_WIDTH and
                    not motion_blurred(o))

        def is_wall_marker(marker_id):
            return marker_id in WALL

        def is_token_marker(marker_id):
            return marker_id in TOKEN

        def marker_map(o):
            # Turn a marked object into a Marker
            rel_x, rel_y = (o.location[0] - x, o.location[1] - y)
            rot_y = atan2(rel_y, rel_x) - heading
            polar_coord = PolarCoord(
                distance_meters=hypot(rel_x, rel_y),
                rot_y_rad=rot_y,
                rot_y_deg=degrees(rot_y)
            )

            # TODO: Check polar coordinates are the right way around
            mid = o.marker_id
            return Marker(
                id=mid,
                size=MARKER_SIZES[mid],
                is_wall_marker=lambda: is_wall_marker(mid),
                is_token_marker=lambda: is_token_marker(mid),
                polar=polar_coord,
            )

        return sorted([marker_map(obj) for obj in self.robot.arena.objects if
                object_filter(obj)],key=lambda m:m.polar.distance_meters)

class ServoBoard(object):
    def __init__(self, robot):
        pass

    @property
    def servos(self):
        return []

class SimRobot(GameObject):
    width = 0.3

    surface_name = 'sb/robot.png'

    _holding = None

    ## Constructor ##

    @property
    def location(self):
        with self.lock:
            return self._body.position

    @location.setter
    def location(self, new_pos):
        with self.lock:
            self._body.position = new_pos

    @property
    def heading(self):
        with self.lock:
            return self._body.angle

    @heading.setter
    def heading(self, new_heading):
        with self.lock:
            self._body.angle = new_heading

    def _send_ultrasound_ping(self, angle_offset):
        with self.arena.physics_lock:
            world = self._body.world

            centre_point = self._body.world_center

            spread_casts = 10
            spread_maximum_angle_radians = radians(10)

            cast = []
            cast_range = 4.0

            for spread_offset in [
                spread_maximum_angle_radians * (x / spread_casts)
                for x in range(-spread_casts, spread_casts + 1)
            ]:
                cast_angle = self._body.angle + angle_offset + spread_offset

                target_point = [
                    centre_point[0] + cast_range * cos(cast_angle),
                    centre_point[1] + cast_range * sin(cast_angle),
                ]

                cast.extend(world.ray_cast(centre_point, target_point))

        if not cast:
            return None

        # Sort by fraction along the ray
        cast.sort(key=lambda x: x[3])

        fixture, intercept_point, _, fraction = cast[0]

        distance_to_intercept = fraction * cast_range

        return distance_to_intercept

    def __init__(self, simulator):
        self._body = None
        self.zone = 0
        super(SimRobot, self).__init__(simulator.arena)
        make_body = simulator.arena._physics_world.create_body
        half_width = self.width * 0.5
        with self.arena.physics_lock:
            self._body = make_body(position=(0, 0),
                                   angle=0,
                                   linear_damping=0.0,
                                   angular_damping=0.0,
                                   type=pypybox2d.body.Body.DYNAMIC)
            self._body.create_polygon_fixture([(-half_width, -half_width),
                                               (half_width, -half_width),
                                               (half_width, half_width),
                                               (-half_width, half_width)],
                                              density=500 * 0.12)  # MDF @ 12cm thickness
        simulator.arena.objects.append(self)
        self.motor_board = MotorBoard(self)
        self.servo_board = ServoBoard(self)
        self.arduino = Arduino(self)

    @property
    def motor_boards(self):
        return BoardList([self.motor_board])

    @property
    def servo_boards(self):
        return BoardList([self.servo_board])

    ## Internal methods ##

    def _apply_wheel_force(self, y_position, power=COAST):
        location_world_space = self._body.get_world_point((0, y_position))
        if power != COAST:
            force_magnitude = power * 100 * 0.6
            frict_multiplier = 50.2
        else:
            force_magnitude = 0
            frict_multiplier = 5.2

        # account for friction
        frict_world = self._body.get_linear_velocity_from_local_point(
            (0, y_position))
        frict_x, frict_y = self._body.get_local_vector(frict_world)

        force_magnitude -= frict_x * frict_multiplier
        force_world_space = (force_magnitude * cos(self.heading),
                             force_magnitude * sin(self.heading))
        self._body.apply_force(force_world_space, location_world_space)


    ## "Public" methods for simulator code ##

    def tick(self, time_passed):
        with self.lock, self.arena.physics_lock:
            half_width = self.width * 0.5
            # left wheel
            self._apply_wheel_force(-half_width, self.motor_board.motors[0])
            # right wheel
            self._apply_wheel_force(half_width, self.motor_board.motors[1])
            # kill the lateral velocity
            right_normal = self._body.get_world_vector((0, 1))
            lateral_vel = (right_normal.dot(self._body.linear_velocity) *
                           right_normal)
            impulse = self._body.mass * -lateral_vel
            self._body.apply_linear_impulse(impulse, self._body.world_center)

    ## "Public" methods for user code ##

    def grab(self):
        if self._holding is not None:
            raise AlreadyHoldingSomethingException()

        with self.lock:
            x, y = self.location
            heading = self.heading

        def object_filter(o):
            rel_x, rel_y = (o.location[0] - x, o.location[1] - y)
            direction = atan2(rel_y, rel_x)
            rel_heading = (direction - heading)

            if rel_heading > math.pi:
                rel_heading -= 2*math.pi
            elif rel_heading < math.pi:
                rel_heading += 2*math.pi

            return (o.grabbable and
                    hypot(rel_x, rel_y) <= GRAB_RADIUS and
                    -HALF_GRAB_SECTOR_WIDTH < rel_heading < HALF_GRAB_SECTOR_WIDTH and
                    not o.grabbed)

        objects = list(filter(object_filter, self.arena.objects))
        if objects:
            self._holding = objects[0]
            if hasattr(self._holding, '_body'):
                with self.lock, self.arena.physics_lock:
                    self._holding_joint = self._body._world.create_weld_joint(
                        self._body,
                        self._holding._body,
                        local_anchor_a=(
                            GRABBER_OFFSET, 0),
                        local_anchor_b=(0, 0))
            self._holding.grab()
            return True
        else:
            return False

    def release(self):
        if self._holding is not None:
            self._holding.release()
            if hasattr(self._holding, '_body'):
                with self.lock, self.arena.physics_lock:
                    self._body.world.destroy_joint(self._holding_joint)
                self._holding_joint = None
            self._holding = None
            return True
        else:
            return False


class BoardList:
    """A mapping of ``Board``s allowing access by index or identity."""

    def __init__(self, board_list):
        self._store_list = board_list

    def __getitem__(self, attr):
        return self._store_list[attr]

    def __iter__(self):
        return iter(self._store_list)

    def __len__(self):
        return len(self._store_list)