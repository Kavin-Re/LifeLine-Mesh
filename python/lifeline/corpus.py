"""Built-in corpus of SYNTHETIC short emergency messages, written by hand for this project (not scraped, not real traffic).
EN = English, HI = Hindi in Roman transliteration ("Hinglish"; no Devanagari). Used only to train/evaluate the codec.
The dictionary (codec.DICT_*) was written BEFORE this corpus from general emergency vocabulary; the corpus deliberately
contains out-of-dictionary words (names, places, rare terms) so the literal-escape path is exercised.
Caveat: one author, ~200 messages -> compression numbers say how the scheme behaves on THIS style of text, not on real traffic."""

EN = """
help trapped under rubble second floor 3 people
urgent need water 40 people at school gym
injured man bleeding need medic at bridge road
building collapsed near market many people trapped
we are safe at the temple 12 people
need insulin for diabetic patient urgent
road blocked by landslide near km 14
flood water rising fast move to roof
family of 5 stranded on roof need boat
pregnant woman in labour need ambulance now
no food for 2 days children hungry
all ok at camp 3 need blankets
fire at warehouse behind station send help
gas leak smell near school evacuate
bridge damaged do not cross
need doctor at village clinic many injured
elderly man unconscious please send medic
2 children missing last seen near river
water level 2 meters at sector 7
hospital has no power need fuel for generator
sos trapped basement 4 people water rising
requesting rescue boat at ramesh nagar lane 3
shelter full need tents for 60 families
medicine shortage fever and diarrhoea spreading
power lines down on main road danger
safe route north via hill road open
helicopter needed for injured at mountain top village
radio working at camp 2 channel 5
need batteries and torches for night search
house collapsed 2 dead 3 injured need help
food distribution at school ground at 5 pm
clean water tanker arrived at market
bleeding not stopping need bandage and first aid
all safe we are at the roof of the community hall
stranded 20 people on bridge need rescue
doctor needed at camp 4 for pregnant women
fuel for boat needed at jetty
oxygen cylinder needed for patient at home
road to hospital cleared ambulance can pass
aftershock felt building cracks evacuate now
looking for sharma family last seen at colony 9
baby needs milk and medicine
we have 15 injured at temple need doctor
volunteers needed to clear debris at lane 5
trapped in car water rising need help
help us we have no water since 3 days
fire spreading towards houses send fire team
need rope and ladder to reach second floor
2 people trapped in lift building 6
small boat arrived at north gate thanks
power restored at hospital
bridge washed away village cut off
need food packets for 100 people at camp 1
missing person arjun age 8 blue shirt
crowd at relief point need police
landslide blocked highway near tunnel
need stretcher and 4 volunteers at lane 12
child with high fever need medicine
we are 6 people on third floor safe but no food
dam water released move to high ground
medical team arriving in 2 hours
need generator and fuel at clinic
sector 5 all clear no injured
water is contaminated do not drink
require blood o negative at district hospital
camp 2 running out of water send tanker
helicopter landing at school ground clear area
rescue team at building 3 searching
patient needs dialysis urgent transport
roof leaking tents damaged need plastic sheets
elderly woman stuck on first floor need help
4 injured at crossing need ambulance
smoke from basement fire call fire brigade
bridge open for light vehicles only
all 30 people evacuated from school
trapped under beam leg injured
need torch and batteries
send boat to mill road 8 people on roof
food and water reached camp 5 thank you
road open to hospital via east gate
need tent and blankets for 20 people
status update camp 3 total 85 people 6 injured
dead body found near canal inform police
cut off no road need airdrop of food
mobile network down need radio at village
heavy rain again water rising at colony
doctor arrived at camp 1
looking for my mother age 70 name sita devi
shop open at market selling bread and water
trapped in toilet 2nd floor 3 people alive
need cutter to break door people inside
fever cases rising at camp need medicine
bridge collapsed near dam
safe house at hill top 25 beds free
transport needed for 10 elderly at old age home
rescued 12 people from roof now at school
fire out no injured
clinic needs oxygen and saline
stranded bus on highway 40 passengers need food
snake bite need antivenom at village
need volunteers with boats at lane 4
water entering ground floor move upstairs
please send help
we are safe
need water
injured
trapped 2 people
need medicine urgent
all ok
need food and water at camp
road blocked
fire near school
need doctor
send boat
help trapped
flood at village
people need rescue
need shelter
bridge down
need ambulance
status ok at camp 2
collapsed building near station help
need blankets
water level rising
need fuel
missing child
gas smell
no power at hospital
need oxygen
rescue needed at lane 9
helicopter needed
""".strip().split("\n")

HI = """
madad chahiye 5 log phanse hain malba mein
pani aur khana nahi hai 2 din se
ghayal bachche ko aspatal pahunchao jaldi
baadh ka pani badh raha hai chhat par jao
doctor ki zaroorat hai camp mein
sab theek hain hum surakshit hain
bijli band hai aspatal mein diesel chahiye
sadak band hai pahad se malba gira
buzurg aadmi behosh hai jaldi doctor bhejo
2 bachche gum hain nadi ke paas
naav bhejo 8 log chhat par hain
dawai chahiye bukhar bahut hai
imarat gir gayi andar log phanse hain
pul toot gaya gaon kat gaya hai
khana aur pani camp 3 mein pahunch gaya
garbhwati mahila ko ambulance chahiye abhi
aag lagi hai godam ke paas fauj bhejo
kambal aur tambu chahiye 30 log hain
raasta khula hai aspatal tak
madad karo
pani chahiye
hum surakshit hain
ghayal log hain doctor bhejo
bachao hum phanse hain
khana nahi hai bachche bhukhe hain
ghar mein pani bhar gaya hai upar aa gaye
helicopter chahiye ghayal ke liye
camp mein 40 log hain khana chahiye
aaj raat tak raahat pahunchegi
sadak par ped gira hai raasta band hai
mere pitaji ghayal hain aspatal le jao
pehli manzil par 3 log phanse hain jaldi aao
saans nahi aa rahi oxygen chahiye
pani peene layak nahi hai mat piyo
police bhejo bheed bahut hai
sab log nikal gaye school khali hai
bijli aa gayi hai camp mein
dawai mil gayi shukriya
bukhar aur dast ke mareez badh rahe hain
pul band hai doosra raasta lo
""".strip().split("\n")

def split_train_test(msgs, test_every=4):
    """Deterministic hold-out: every 4th message (index % 4 == 3) is test."""
    tr = [m for i, m in enumerate(msgs) if i % test_every != test_every - 1]
    te = [m for i, m in enumerate(msgs) if i % test_every == test_every - 1]
    return tr, te
