from __future__ import print_function

import logging

import grpc
import mafia_game_pb2
import mafia_game_pb2_grpc
import asyncio
from simple_term_menu import TerminalMenu
import time
import sys
import random
class Client:
    def __init__(self):
        self.user_name = ''
        self.room_id = 0
        channel = 'localhost:50053'
        self.stub = mafia_game_pb2_grpc.ServerStub(grpc.aio.insecure_channel(channel))
        self.role = ''
        self.hometask_checking_mode = False

    def get_room_id(self):
        return self.room_id

    async def install_room_id(self, room_validation):
        if not room_validation:
            response = await self.stub.GetRoomId(mafia_game_pb2.EmptyRequest(room_id=self.room_id))
            self.room_id = response.room_id
        else:
            response_val = False
            while not response_val:
                room_id = int(input("Enter room_id: "))
                self.room_id = room_id
                response = await self.stub.GetRoomId(mafia_game_pb2.EmptyRequest(room_id=self.room_id))
                response_val = response.validation
                if not response_val:
                    print("Room id is incorrect. Try agian")

    async def user_initializitaion(self, user_name, room_id):
        self.user_name = user_name
        self.room_id = room_id
        await self.stub.InstallName(mafia_game_pb2.NameRequest(name=self.user_name, room_id=self.room_id))

    async def start_process(self):
        tasks = [self.game_awaiting(), self.getting_notifications()]
        await asyncio.gather(*tasks)

    async def getting_notifications(self):
        stub = self.stub
        async for note in stub.GetStream(mafia_game_pb2.RoomResponse(room_id=self.room_id)):
            print(note.message, flush=True)

    async def game_awaiting(self):
        await self.stub.StartTheGameRequest(mafia_game_pb2.EmptyRequest(room_id=self.room_id))
        time.sleep(2)
        response = await self.stub.RoleAssignment(mafia_game_pb2.NameRequest(name=self.user_name, room_id=self.room_id))
        time.sleep(1)

        print("Your role: ", response.role, flush=True)
        self.role = response.role

        day_round = 1
        night_round = 1
        show_mafia = False

        while True:
            if day_round != 1:
                print("⭐️Day ", str(day_round), "⭐️", flush=True)

                permission = False
                if self.role == 'officer' and show_mafia and not self.hometask_checking_mode:
                    print("Would you like to show mafia?")
                    options = ["Yes", "No"]
                    terminal_menu = TerminalMenu(options)
                    menu_chosen_option = terminal_menu.show()

                    if options[menu_chosen_option] == "Yes":
                        permission = True

                ### hometask_checking_mode - we will always show mafia
                ### after night if the officer found one
                if self.role == 'officer' and show_mafia and self.hometask_checking_mode:
                    permission = True
                ###

                await self.stub.AnnounceMafia(mafia_game_pb2.AnnounceMafiaRequest(permission=permission, room_id=self.room_id))
                time.sleep(1)

                print("📍Voting📍", flush=True)
                while True:
                    if self.role != 'ghost':

                        response = await self.stub.UsersInfo(mafia_game_pb2.NameRequest(name=self.user_name, room_id=self.room_id))
                        users = response.names.split(',')
                        statuses = response.statuses.split(',')
                        alive_users = []
                        for i in range(len(users)):
                            if statuses[i] == 'alive':
                                alive_users += users[i]

                        if self.hometask_checking_mode:
                            person_to_vote = random.choice(alive_users)
                            await self.stub.AccusePerson(mafia_game_pb2.AccuseRequest(username=self.user_name, name=person_to_vote, room_id=self.room_id))

                        else:
                            options = ["Show users info", "Accuse somebody"]
                            terminal_menu = TerminalMenu(options)
                            menu_chosen_option = terminal_menu.show()

                            if options[menu_chosen_option] == "Show users info":
                                for i in range(len(users)):
                                    print(users[i], ': ', statuses[i], flush=True)
                                continue

                            elif options[menu_chosen_option] == "Accuse somebody":
                                terminal_menu = TerminalMenu(alive_users)
                                menu_chosen_option = terminal_menu.show()
                                await self.stub.AccusePerson(mafia_game_pb2.AccuseRequest(username=self.user_name, name=alive_users[menu_chosen_option], room_id=self.room_id))

                    response = await self.stub.EndDayRequest(mafia_game_pb2.EmptyRequest(room_id=self.room_id))
                    if response.message == self.user_name:
                        self.role = "ghost"
                    break

            day_round += 1
            await self.stub.CleanAccusedRequest(mafia_game_pb2.EmptyRequest(room_id=self.room_id))
            time.sleep(0.2)

            response = await self.stub.CheckGameEnding(mafia_game_pb2.EmptyRequest(room_id=self.room_id))
            if not response.right:
                print(response.message)
                break

            print("🌌 Night ", str(night_round), "🌌", flush=True)

            while True:
                response = await self.stub.UsersInfo(mafia_game_pb2.NameRequest(name=self.user_name, room_id=self.room_id))
                users = response.names.split(',')
                statuses = response.statuses.split(',')
                alive_users = []
                for i in range(len(users)):
                    if statuses[i] == 'alive':
                        alive_users += users[i]

                if self.role == 'mafia':

                    if self.hometask_checking_mode:
                        person_to_kill = random.choice(alive_users)
                        await self.stub.KillPerson(mafia_game_pb2.NameRequest(name=person_to_kill, room_id=self.room_id))

                    else:
                        options = ["Show users info", "Choose person to kill"]
                        terminal_menu = TerminalMenu(options)
                        menu_chosen_option = terminal_menu.show()

                        if options[menu_chosen_option] == "Show users info":
                            for i in range(len(users)):
                                print(users[i], ': ', statuses[i], flush=True)
                            continue

                        elif options[menu_chosen_option] == "Choose person to kill":
                            response = await self.stub.GetVictims(mafia_game_pb2.NameRequest(name=self.user_name, room_id=self.room_id))
                            victims = response.names.split(',')
                            terminal_menu = TerminalMenu(victims)
                            menu_chosen_option = terminal_menu.show()
                            await self.stub.KillPerson(mafia_game_pb2.NameRequest(name=victims[menu_chosen_option], room_id=self.room_id))

                elif self.role == 'officer':

                    if self.hometask_checking_mode:
                        person_to_check = random.choice(alive_users)
                        response = await self.stub.CheckPerson(mafia_game_pb2.NameRequest(name=person_to_check, room_id=self.room_id))
                        print(response.message)
                        show_mafia = response.right
                    else:
                        options = ["Show users info", "Check person"]
                        terminal_menu = TerminalMenu(options)
                        menu_chosen_option = terminal_menu.show()

                        if options[menu_chosen_option] == "Show users info":
                            for i in range(len(users)):
                                print(users[i], ': ', statuses[i], flush=True)
                            continue

                        elif options[menu_chosen_option] == "Check person":
                            terminal_menu = TerminalMenu(alive_users)
                            menu_chosen_option = terminal_menu.show()
                            response = await self.stub.CheckPerson(mafia_game_pb2.NameRequest(name=alive_users[menu_chosen_option], room_id=self.room_id))
                            print(response.message)
                            show_mafia = response.right

                response = await self.stub.EndNightRequest(mafia_game_pb2.EmptyRequest(room_id=self.room_id))
                if response.message == self.user_name:
                    self.role = "ghost"
                break

            await self.stub.CleanAccusedRequest(mafia_game_pb2.EmptyRequest(room_id=self.room_id))
            time.sleep(0.2)
            night_round += 1

            response = await self.stub.CheckGameEnding(mafia_game_pb2.EmptyRequest(room_id=self.room_id))
            if not response.right:
                print(response.message)
                break

async def run(hometask_checking_mode):
    client = Client()

    if not hometask_checking_mode:
        print("Do you have a room id? If no, we will provide you one")
        options = ["Yes", "No"]
        terminal_menu = TerminalMenu(options)
        menu_chosen_option = terminal_menu.show()
    if hometask_checking_mode or options[menu_chosen_option] == "No":
        await client.install_room_id(False)
        room_id = client.get_room_id()
        print("Your room id is: ", room_id)
    else:
        await client.install_room_id(True)
        room_id = client.get_room_id()

    while True:
        name = input("Print your name: ")
        response = await client.stub.UsersInfo(mafia_game_pb2.NameRequest(name="", room_id=client.room_id))
        users = response.names.split(',')
        if name in users:
            print("This name already exists")
        else:
            break
    client.hometask_checking_mode = hometask_checking_mode
    await client.user_initializitaion(name, room_id)
    await client.start_process()

if __name__ == "__main__":
    arguments = sys.argv
    hometask_checking_mode = False
    if len(arguments) > 1:
        hometask_checking_mode = True
    asyncio.run(run(hometask_checking_mode))
