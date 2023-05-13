from concurrent import futures
import logging

import grpc
import mafia_game_pb2
import mafia_game_pb2_grpc

import asyncio
from grpc import aio
import threading
from threading import Lock
import time
import random
import collections
from collections import defaultdict

NUMBER_OF_MEMBERS = 6

class Room:
    def __init__(self):
        self.users2role = {}
        self.chats = []
        self.roles = ['mafia', 'citizen', 'officer', 'citizen', 'mafia', 'citizen']
        self.game_started = False

        self.starting_game_cv = asyncio.Condition()
        self.mutex = Lock()

        self.user2status = {}

        self.accused = defaultdict(int)
        self.day_cv = asyncio.Condition()
        self.person_accused = ""

        self.night_cv = asyncio.Condition()
        self.waiting = 0

        self.anounce_waiting = 0
        self.announce_cv = asyncio.Condition()
        self.announce = False
        self.officer_mafia = []

        self.game_is_played = True

class Server(mafia_game_pb2_grpc.ServerServicer):
    def __init__(self):
        self.rooms = {}
        self.room_ids = set()
        self.room_mutex = Lock()
        self.not_filled_rooms = defaultdict(int)
        for room_id in range(20000, 100000):
            self.room_ids.add(room_id)
            self.rooms[room_id] = Room()

    async def InstallName(self, request, context):
        room = self.rooms[request.room_id]
        room.users2role[request.name] = ''
        room.user2status[request.name] = 'alive'
        room.chats.append(mafia_game_pb2.Reply(message='%s joined the game' % request.name))
        return mafia_game_pb2.Reply(message='Hello, %s!' % request.name)

    async def GetRoomId(self, request, context):
        self.room_mutex.acquire()
        room_id = request.room_id

        # room validation
        if room_id != 0 and room_id not in self.rooms:
            self.room_mutex.release()
            return mafia_game_pb2.RoomResponse(room_id=room_id, validation=False)

        # room_id is correct, register person
        if request.room_id != 0:
            self.not_filled_rooms[room_id] += 1
            if self.not_filled_rooms[room_id] == NUMBER_OF_MEMBERS:
                self.not_filled_rooms.pop(room_id, None)
            self.room_mutex.release()
            return mafia_game_pb2.RoomResponse(room_id=room_id, validation=True)

        # person does not have a room, but there are people in not filled rooms
        if len(self.not_filled_rooms) != 0:
            room_id = random.choice(list(self.not_filled_rooms.keys()))
            self.not_filled_rooms[room_id] += 1
            if self.not_filled_rooms[room_id] == NUMBER_OF_MEMBERS:
                self.not_filled_rooms.pop(room_id, None)
        else:
            room_id = random.choice(list(self.room_ids))
            self.room_ids.remove(room_id)
            self.not_filled_rooms[room_id] = 1
        self.room_mutex.release()
        return mafia_game_pb2.RoomResponse(room_id=room_id, validation=True)

    async def GetStream(self, request, context):
        i = 0
        room = self.rooms[request.room_id]
        while True and room.game_is_played:
            if i < len(room.chats):
                i += 1
                yield room.chats[i - 1]
            else:
                # suspend the current task and give an opportunity to other tasks to run
                await asyncio.sleep(1)

    async def StartTheGameRequest(self, request, context):
        room = self.rooms[request.room_id]
        if len(room.users2role) != NUMBER_OF_MEMBERS:
            async with room.starting_game_cv:
                await room.starting_game_cv.wait()
        else:
            async with room.starting_game_cv:
                room.starting_game_cv.notify_all()

        if not room.game_started:
            room.chats.append(mafia_game_pb2.Reply(message='🎉 Starting the game! 🎉'))
            room.game_started = True

        return mafia_game_pb2.EmptyResponse()

    async def RoleAssignment(self, request, context):
        room = self.rooms[request.room_id]
        room.mutex.acquire()
        room.users2role[request.name] = room.roles.pop()
        room.mutex.release()
        return mafia_game_pb2.Role(role=room.users2role[request.name])

    async def UsersInfo(self, request, context):
        room = self.rooms[request.room_id]
        users = ""
        statuses = ""
        for name, status in room.user2status.items():
            if name != request.name:
                users += name + ','
                statuses += status + ','
        return mafia_game_pb2.UsersInfoMessage(names=users[:-1], statuses=statuses[:-1])

    async def GetVictims(self, request, context):
        room = self.rooms[request.room_id]
        users = ""
        for name, role in room.users2role.items():
            if name != request.name and role != 'mafia':
                users += name + ','
        return mafia_game_pb2.UsersInfoMessage(names=users[:-1], statuses="")

    def ChooseRandomPersonForKilling(room_id):
        room = self.rooms[room_id]
        citizens = []
        for username, role in room.users2role.items():
            if role == "citizen":
                citizens.append(username)
        room.person_accused = random.choice(citizens)
        room.user2status[room.person_accused] = "ghost"
        room.users2role.pop(room.person_accused, None)
        return

    async def AccusePerson(self, request, context):
        room = self.rooms[request.room_id]
        accused_person = request.name
        if accused_person in room.accused:
            room.accused[accused_person] += 1
        else:
            room.accused[accused_person] = 1
        room.chats.append(mafia_game_pb2.Reply(message=request.username + ' has accused somebody.'))
        return mafia_game_pb2.EmptyResponse()

    async def KillPerson(self, request, context):
        room = self.rooms[request.room_id]
        accused_person = request.name
        if accused_person in room.accused:
            room.accused[accused_person] += 1
        else:
            room.accused[accused_person] = 1
        return mafia_game_pb2.EmptyResponse()

    async def CheckPerson(self, request, context):
        room = self.rooms[request.room_id]
        person_to_check = request.name
        if room.users2role[person_to_check] == 'mafia':
            room.officer_mafia.append(person_to_check)
            return mafia_game_pb2.BoolReply(message='You are right.%s is mafia' % person_to_check, right=True)
        return mafia_game_pb2.BoolReply(message='%s is not mafia' % person_to_check, right=len(room.officer_mafia))

    async def EndNightRequest(self, request, context):
        room = self.rooms[request.room_id]
        room.waiting += 1
        if room.waiting != NUMBER_OF_MEMBERS:
            async with room.night_cv:
                await room.night_cv.wait()
                time.sleep(0.2)
        else:
            async with room.night_cv:
                room.night_cv.notify_all()

        if room.person_accused:
            return mafia_game_pb2.Reply(message=room.person_accused)

        people_with_max_votes = []
        max_votes = max(room.accused.values())
        for username, votes in room.accused.items():
            if votes == max_votes:
                people_with_max_votes.append(username)

        room.person_accused = random.choice(people_with_max_votes)
        room.user2status[room.person_accused] = "ghost"
        room.users2role.pop(room.person_accused, None)
        room.chats.append(mafia_game_pb2.Reply(message='Today we have killed: %s' % room.person_accused))
        room.accused = {}
        room.waiting = 0
        return mafia_game_pb2.Reply(message=room.person_accused)

    async def EndDayRequest(self, request, context):
        room = self.rooms[request.room_id]
        room.waiting += 1
        if room.waiting != NUMBER_OF_MEMBERS:
            async with room.day_cv:
                await room.day_cv.wait()
                time.sleep(0.2)
        else:
            async with room.day_cv:
                room.day_cv.notify_all()

        if room.person_accused:
            return mafia_game_pb2.Reply(message=room.person_accused)

        people_with_max_votes = []
        max_votes = max(room.accused.values())
        for username, votes in room.accused.items():
            if votes == max_votes:
                people_with_max_votes.append(username)

        room.person_accused = random.choice(people_with_max_votes)

        room.user2status[room.person_accused] = "ghost"
        room.users2role.pop(room.person_accused, None)
        room.chats.append(mafia_game_pb2.Reply(message='Today we have accused: %s' % room.person_accused))
        room.accused = {}
        room.waiting = 0
        if room.person_accused in room.officer_mafia:
            room.officer_mafia.remove(room.person_accused)
        return mafia_game_pb2.Reply(message=room.person_accused)

    async def CleanAccusedRequest(self, request, context):
        room = self.rooms[request.room_id]
        room.person_accused = ""
        return mafia_game_pb2.EmptyResponse()

    async def AnnounceMafia(self, request, context):
        room = self.rooms[request.room_id]
        room.anounce_waiting += 1
        room.announce |= request.permission
        room.announce &= (len(room.officer_mafia) != 0)
        if room.anounce_waiting != NUMBER_OF_MEMBERS:
            async with room.announce_cv:
                await room.announce_cv.wait()
                time.sleep(0.2)
        else:
            async with room.announce_cv:
                room.announce_cv.notify_all()
        if room.announce:
            room.announce = False
            room.chats.append(mafia_game_pb2.Reply(message='The officer found out that %s is mafia' % room.officer_mafia.pop()))
        room.anounce_waiting = 0
        return mafia_game_pb2.EmptyResponse()

    async def CheckGameEnding(self, request, context):
        room = self.rooms[request.room_id]
        count_mafia = 0
        count_citizens = 0
        for _, role in room.users2role.items():
            if role != 'mafia':
                count_citizens += 1
            else:
                count_mafia += 1
        message = ''
        if count_mafia == 0:
            message = 'Citizens won'
            room.game_is_played = False
        elif count_mafia == count_citizens:
            message = 'Mafia won'
            room.game_is_played = False

        right = room.game_is_played
        if not right:
            self.room_mutex.acquire()
            self.room_ids.add(request.room_id)
            self.room_mutex.release()
        return mafia_game_pb2.BoolReply(message=message, right=right)


async def serve():
    port = '50053'
    server = aio.server()
    mafia_game_pb2_grpc.add_ServerServicer_to_server(Server(), server)
    server.add_insecure_port('[::]:' + port)
    print("Server started, listening on " + port)
    await server.start()
    await server.wait_for_termination()


if __name__ == '__main__':
    asyncio.run(serve())
