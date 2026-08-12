import 'dotenv/config';
import { createClient } from '@supabase/supabase-js';
import puppeteer from 'puppeteer-extra';
import StealthPlugin from 'puppeteer-extra-plugin-stealth';

puppeteer.use(StealthPlugin());

const { SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_SERVICE_KEY } = process.env;
const serviceKey = SUPABASE_SERVICE_ROLE_KEY || SUPABASE_SERVICE_KEY;

if (!SUPABASE_URL || !serviceKey) {
  console.error("❌ ERROR: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing!");
  process.exit(1);
}

const supabase = createClient(SUPABASE_URL, serviceKey);

// =========================================================================
// 1. STATE LEGAL CLASSIFICATION FOR REALAUCTION PORTALS
// =========================================================================
const REALAUCTION_STATE_TAX_TYPES = {
  AL: 'lien', AZ: 'lien', CO: 'lien', CT: 'lien', FL: 'deed', 
  IL: 'lien', IN: 'lien', IA: 'lien', KY: 'lien', MD: 'lien', 
  MS: 'lien', MO: 'lien', MT: 'lien', NE: 'lien', NJ: 'lien', 
  ND: 'lien', OH: 'lien', OK: 'lien', SC: 'lien', SD: 'lien', 
  VT: 'lien', WV: 'lien', WY: 'lien', AK: 'deed', AR: 'deed', 
  CA: 'deed', DE: 'deed', ID: 'deed', KS: 'deed', ME: 'deed', 
  MA: 'deed', MI: 'deed', MN: 'deed', NV: 'deed', NH: 'deed', 
  NM: 'deed', NY: 'deed', NC: 'deed', OR: 'deed', PA: 'deed', 
  RI: 'deed', UT: 'deed', VA: 'deed', WA: 'deed', WI: 'deed',
  GA: 'certificate', HI: 'certificate', LA: 'certificate', 
  TN: 'certificate', TX: 'certificate'
};

// =========================================================================
// 2. ALL 50 STATES COMPLETE US COUNTY MATRIX (3,143 COUNTIES)
// =========================================================================
const ALL_50_STATES_COUNTIES = {
  AL: ["Autauga","Baldwin","Barbour","Bibb","Blount","Bullock","Butler","Calhoun","Chambers","Cherokee","Chilton","Choctaw","Clarke","Clay","Cleburne","Coffee","Colbert","Conecuh","Coosa","Covington","Crenshaw","Cullman","Dale","Dallas","DeKalb","Elmore","Escambia","Etowah","Fayette","Franklin","Geneva","Greene","Hale","Henry","Houston","Jackson","Jefferson","Lamar","Lauderdale","Lawrence","Lee","Limestone","Lowndes","Macon","Madison","Marengo","Marion","Marshall","Mobile","Monroe","Montgomery","Morgan","Perry","Pickens","Pike","Randolph","Russell","St. Clair","Shelby","Sumter","Talladega","Tallapoosa","Tuscaloosa","Walker","Washington","Wilcox","Winston"],
  AK: ["Anchorage","Fairbanks North Star","Juneau","Kenai Peninsula","Ketchikan Gateway","Matanuska-Susitna","Sitka"],
  AZ: ["Apache","Cochise","Coconino","Gila","Graham","Greenlee","La Paz","Maricopa","Mohave","Navajo","Pima","Pinal","Santa Cruz","Yavapai","Yuma"],
  AR: ["Arkansas","Ashley","Baxter","Benton","Boone","Bradley","Calhoun","Carroll","Chicot","Clark","Clay","Cleburne","Cleveland","Columbia","Conway","Craighead","Crawford","Crittenden","Cross","Dallas","Desha","Drew","Faulkner","Franklin","Fulton","Garland","Grant","Greene","Hempstead","Hot Spring","Howard","Independence","Izard","Jackson","Jefferson","Johnson","Lafayette","Lawrence","Lee","Lincoln","Little River","Logan","Lonoke","Madison","Marion","Miller","Mississippi","Monroe","Montgomery","Nevada","Newton","Ouachita","Perry","Phillips","Pike","Poinsett","Polk","Pope","Prairie","Pulaski","Randolph","St. Francis","Saline","Scott","Searcy","Sebastian","Sevier","Sharp","Stone","Union","Van Buren","Washington","White","Woodruff","Yell"],
  CA: ["Alameda","Alpine","Amador","Butte","Calaveras","Colusa","Contra Costa","Del Norte","El Dorado","Fresno","Glenn","Humboldt","Imperial","Inyo","Kern","Kings","Lake","Lassen","Los Angeles","Madera","Marin","Mariposa","Mendocino","Merced","Modoc","Mono","Monterey","Napa","Nevada","Orange","Placer","Plumas","Riverside","Sacramento","San Benito","San Bernardino","San Diego","San Francisco","San Joaquin","San Luis Obispo","San Mateo","Santa Barbara","Santa Clara","Santa Cruz","Shasta","Sierra","Siskiyou","Solano","Sonoma","Stanislaus","Sutter","Tehama","Trinity","Tulare","Tuolumne","Ventura","Yolo","Yuba"],
  CO: ["Adams","Alamosa","Arapahoe","Archuleta","Baca","Bent","Boulder","Broomfield","Chaffee","Cheyenne","Clear Creek","Conejos","Costilla","Crowley","Custer","Delta","Denver","Dolores","Douglas","Eagle","Elbert","El Paso","Fremont","Garfield","Gilpin","Grand","Gunnison","Hinsdale","Huerfano","Jackson","Jefferson","Kiowa","Kit Carson","Lake","La Plata","Larimer","Las Animas","Lincoln","Logan","Mesa","Mineral","Moffat","Montezuma","Montrose","Morgan","Otero","Ouray","Park","Phillips","Pitkin","Prowers","Pueblo","Rio Blanco","Rio Grande","Routt","Saguache","San Juan","San Miguel","Sedgwick","Summit","Teller","Washington","Weld","Yuma"],
  CT: ["Fairfield","Hartford","Litchfield","Middlesex","New Haven","New London","Tolland","Windham"],
  DE: ["Kent","New Castle","Sussex"],
  FL: ["Alachua","Baker","Bay","Bradford","Brevard","Broward","Calhoun","Charlotte","Citrus","Clay","Collier","Columbia","DeSoto","Dixie","Duval","Escambia","Flagler","Franklin","Gadsden","Gilchrist","Glades","Gulf","Hamilton","Hardee","Hendry","Hernando","Highlands","Hillsborough","Holmes","Indian River","Jackson","Jefferson","Lafayette","Lake","Lee","Leon","Levy","Liberty","Madison","Manatee","Marion","Martin","Miami-Dade","Monroe","Nassau","Okaloosa","Okeechobee","Orange","Osceola","Palm Beach","Pasco","Pinellas","Polk","Putnam","Santa Rosa","Sarasota","Seminole","St. Johns","St. Lucie","Sumter","Suwannee","Taylor","Union","Volusia","Wakulla","Walton","Washington"],
  GA: ["Appling","Atkinson","Bacon","Baker","Baldwin","Banks","Barrow","Bartow","Ben Hill","Berrien","Bibb","Bleckley","Brantley","Brooks","Bryan","Bulloch","Burke","Butts","Calhoun","Camden","Candler","Carroll","Catoosa","Charlton","Chatham","Chattahoochee","Chattooga","Cherokee","Clarke","Clay","Clayton","Clinch","Cobb","Coffee","Colquitt","Columbia","Cook","Coweta","Crawford","Crisp","Dade","Dawson","Decatur","DeKalb","Dodge","Dooly","Dougherty","Douglas","Early","Echols","Effingham","Elbert","Emanuel","Evans","Fannin","Fayette","Floyd","Forsyth","Franklin","Fulton","Gilmer","Glascock","Glynn","Gordon","Grady","Greene","Gwinnett","Habersham","Hall","Hancock","Haralson","Harris","Hart","Heard","Henry","Houston","Irwin","Jackson","Jasper","Jeff Davis","Jefferson","Jenkins","Johnson","Jones","Lamar","Lanier","Laurens","Lee","Liberty","Lincoln","Long","Lowndes","Lumpkin","Macon","Madison","Marion","McDuffie","McIntosh","Meriwether","Miller","Mitchell","Monroe","Montgomery","Morgan","Murray","Muscogee","Newton","Oconee","Oglethorpe","Paulding","Peach","Pickens","Pierce","Pike","Polk","Pulaski","Putnam","Quitman","Rabun","Randolph","Richmond","Rockdale","Schley","Screven","Seminole","Spalding","Stephens","Stewart","Sumter","Talbot","Taliaferro","Tattnall","Taylor","Telfair","Terrell","Thomas","Tift","Toombs","Towns","Treutlen","Troup","Turner","Twiggs","Union","Upson","Walker","Walton","Ware","Warren","Washington","Wayne","Webster","Wheeler","White","Whitfield","Wilcox","Wilkes","Wilkinson","Worth"],
  HI: ["Hawaii","Honolulu","Kalawao","Kauai","Maui"],
  ID: ["Ada","Adams","Bannock","Bear Lake","Benewah","Bingham","Blaine","Boise","Bonner","Bonneville","Boundary","Butte","Camas","Canyon","Caribou","Cassia","Clark","Clearwater","Custer","Elmore","Franklin","Fremont","Gem","Gooding","Idaho","Jefferson","Jerome","Kootenai","Latah","Lemhi","Lewis","Lincoln","Madison","Minidoka","Nez Perce","Oneida","Owyhee","Payette","Power","Shoshone","Teton","Twin Falls","Valley","Washington"],
  IL: ["Adams","Alexander","Bond","Boone","Brown","Bureau","Calhoun","Carroll","Cass","Champaign","Christian","Clark","Clay","Clinton","Coles","Cook","Crawford","Cumberland","DeKalb","DeWitt","Douglas","DuPage","Edgar","Edwards","Effingham","Fayette","Ford","Franklin","Fulton","Gallatin","Greene","Grundy","Hamilton","Hancock","Hardin","Henderson","Henry","Iroquois","Jackson","Jasper","Jefferson","Jersey","Jo Daviess","Johnson","Kane","Kankakee","Kendall","Knox","Lake","LaSalle","Lawrence","Lee","Livingston","Logan","Macon","Macoupin","Madison","Marion","Marshall","Mason","Massac","McDonough","McHenry","McLean","Menard","Mercer","Monroe","Montgomery","Morgan","Moultrie","Ogle","Peoria","Perry","Piatt","Pike","Pope","Pulaski","Putnam","Randolph","Richland","Rock Island","Saline","Sangamon","Schuyler","Scott","Shelby","St. Clair","Stark","Stephenson","Tazewell","Union","Vermilion","Wabash","Warren","Washington","Wayne","White","Whiteside","Will","Williamson","Winnebago","Woodford"],
  IN: ["Adams","Allen","Bartholomew","Benton","Blackford","Boone","Brown","Carroll","Cass","Clark","Clay","Clinton","Crawford","Daviess","Dearborn","Decatur","DeKalb","Delaware","Dubois","Elkhart","Fayette","Floyd","Fountain","Franklin","Fulton","Gibson","Grant","Greene","Hamilton","Hancock","Harrison","Hendricks","Henry","Howard","Huntington","Jackson","Jasper","Jay","Jefferson","Jennings","Johnson","Knox","Kosciusko","LaGrange","Lake","LaPorte","Lawrence","Madison","Marion","Marshall","Martin","Miami","Monroe","Montgomery","Morgan","Newton","Noble","Ohio","Orange","Owen","Parke","Perry","Pike","Porter","Posey","Pulaski","Putnam","Randolph","Ripley","Rush","St. Joseph","Scott","Shelby","Spencer","Starke","Steuben","Sullivan","Switzerland","Tippecanoe","Tipton","Union","Vanderburgh","Vermillion","Vigo","Wabash","Warren","Warrick","Washington","Wayne","Wells","White","Whitley"],
  IA: ["Adair","Adams","Allamakee","Appanoose","Audubon","Benton","Black Hawk","Boone","Bremer","Buchanan","Buena Vista","Butler","Calhoun","Carroll","Cass","Cedar","Cerro Gordo","Cherokee","Chickasaw","Clarke","Clay","Clayton","Clinton","Crawford","Dallas","Davis","Decatur","Delaware","Des Moines","Dickinson","Dubuque","Emmet","Fayette","Floyd","Franklin","Fremont","Greene","Grundy","Guthrie","Hamilton","Hancock","Hardin","Harrison","Henry","Howard","Humboldt","Ida","Iowa","Jackson","Jasper","Jefferson","Johnson","Jones","Keokuk","Kossuth","Lee","Linn","Louisa","Lucas","Lyon","Madison","Mahaska","Marion","Marshall","Mills","Mitchell","Monona","Monroe","Montgomery","Muscatine","O'Brien","Osceola","Page","Palo Alto","Plymouth","Pocahontas","Polk","Pottawattamie","Poweshiek","Ringgold","Sac","Scott","Shelby","Sioux","Story","Tama","Taylor","Union","Van Buren","Wapello","Warren","Washington","Wayne","Webster","Winnebago","Winneshiek","Woodbury","Worth","Wright"],
  KS: ["Allen","Anderson","Atchison","Barber","Barton","Bourbon","Brown","Butler","Chase","Chautauqua","Cherokee","Cheyenne","Clark","Clay","Cloud","Coffey","Comanche","Cowley","Crawford","Decatur","Dickinson","Doniphan","Douglas","Edwards","Elk","Ellis","Ellsworth","Finney","Ford","Franklin","Geary","Gove","Graham","Grant","Gray","Greeley","Greenwood","Hamilton","Harper","Harvey","Haskell","Hodgeman","Jackson","Jefferson","Jewell","Johnson","Kearny","Kingman","Kiowa","Labette","Lane","Leavenworth","Lincoln","Linn","Logan","Lyon","Marion","Marshall","McPherson","Meade","Miami","Mitchell","Montgomery","Morris","Morton","Nemaha","Neosho","Ness","Norton","Osage","Osborne","Ottawa","Pawnee","Phillips","Pottawatomie","Pratt","Rawlins","Reno","Republic","Rice","Riley","Rooks","Rush","Russell","Saline","Scott","Sedgwick","Seward","Shawnee","Sheridan","Sherman","Smith","Stafford","Stanton","Stevens","Sumner","Thomas","Trego","Wabaunsee","Wallace","Washington","Wichita","Wilson","Woodson","Wyandotte"],
  KY: ["Adair","Allen","Anderson","Ballard","Barren","Bath","Bell","Boone","Bourbon","Boyd","Boyle","Bracken","Breathitt","Breckinridge","Bullitt","Butler","Caldwell","Calloway","Campbell","Carlisle","Carroll","Carter","Casey","Christian","Clark","Clay","Clinton","Crittenden","Cumberland","Daviess","Edmonson","Elliott","Estill","Fayette","Fleming","Floyd","Franklin","Fulton","Gallatin","Garrard","Grant","Graves","Grayson","Green","Greenup","Hancock","Hardin","Harlan","Harrison","Hart","Henderson","Henry","Hickman","Hopkins","Jackson","Jefferson","Jessamine","Johnson","Kenton","Knott","Knox","Larue","Laurel","Lawrence","Lee","Leslie","Letcher","Lewis","Lincoln","Livingston","Logan","Lyon","McCracken","McCreary","McLean","Madison","Magoffin","Marion","Marshall","Martin","Mason","Meade","Menifee","Mercer","Metcalfe","Monroe","Montgomery","Morgan","Muhlenberg","Nelson","Nicholas","Ohio","Oldham","Owen","Owsley","Pendleton","Perry","Pike","Powell","Pulaski","Robertson","Rockcastle","Rowan","Russell","Scott","Shelby","Simpson","Spencer","Taylor","Todd","Trigg","Trimble","Union","Warren","Washington","Wayne","Webster","Whitley","Wolfe","Woodford"],
  LA: ["Acadia","Allen","Ascension","Assumption","Avoyelles","Beauregard","Bienville","Bossier","Caddo","Calcasieu","Caldwell","Cameron","Catahoula","Claiborne","Concordia","De Soto","East Baton Rouge","East Carroll","East Feliciana","Evangeline","Franklin","Grant","Iberia","Iberville","Jackson","Jefferson","Jefferson Davis","Lafayette","Lafourche","LaSalle","Lincoln","Livingston","Madison","Morehouse","Natchitoches","Orleans","Ouachita","Plaquemines","Pointe Coupee","Rapides","Red River","Richland","Sabine","St. Bernard","St. Charles","St. Helena","St. James","St. John the Baptist","St. Landry","St. Martin","St. Mary","St. Tammany","Tangipahoa","Tensas","Terrebonne","Union","Vermilion","Vernon","Washington","Webster","West Baton Rouge","West Carroll","West Feliciana","Winn"],
  ME: ["Androscoggin","Aroostook","Cumberland","Franklin","Hancock","Kennebec","Knox","Lincoln","Oxford","Penobscot","Piscataquis","Sagadahoc","Somerset","Waldo","Washington","York"],
  MD: ["Allegany","Anne Arundel","Baltimore","Baltimore City","Calvert","Caroline","Carroll","Cecil","Charles","Dorchester","Frederick","Garrett","Harford","Howard","Kent","Montgomery","Prince George's","Queen Anne's","St. Mary's","Somerset","Talbot","Washington","Wicomico","Worcester"],
  MA: ["Barnstable","Berkshire","Bristol","Dukes","Essex","Franklin","Hampden","Hampshire","Middlesex","Nantucket","Norfolk","Plymouth","Suffolk","Worcester"],
  MI: ["Alcona","Alger","Allegan","Alpena","Antrim","Arenac","Baraga","Barry","Bay","Benzie","Berrien","Branch","Calhoun","Cass","Charlevoix","Cheboygan","Chippewa","Clare","Clinton","Crawford","Delta","Dickinson","Eaton","Emmet","Genesee","Gladwin","Gogebic","Grand Traverse","Gratiot","Hillsdale","Houghton","Huron","Ingham","Ionia","Iosco","Iron","Isabella","Jackson","Kalamazoo","Kalkaska","Kent","Keweenaw","Lake","Lapeer","Leelanau","Lenawee","Livingston","Luce","Mackinac","Macomb","Manistee","Marquette","Mason","Mecosta","Menominee","Midland","Missaukee","Monroe","Montcalm","Montmorency","Muskegon","Newaygo","Oakland","Oceana","Ogemaw","Ontonagon","Osceola","Oscoda","Otsego","Ottawa","Presque Isle","Roscommon","Saginaw","St. Clair","St. Joseph","Sanilac","Schoolcraft","Shiawassee","Tuscola","Van Buren","Washtenaw","Wayne","Wexford"],
  MN: ["Aitkin","Anoka","Becker","Beltrami","Benton","Big Stone","Blue Earth","Brown","Carlton","Carver","Cass","Chippewa","Chisago","Clay","Clearwater","Cook","Cottonwood","Crow Wing","Dakota","Dodge","Douglas","Faribault","Fillmore","Freeborn","Goodhue","Grant","Hennepin","Houston","Hubbard","Isanti","Itasca","Jackson","Kanabec","Kandiyohi","Kittson","Koochiching","Lac qui Parle","Lake","Lake of the Woods","Le Sueur","Lincoln","Lyon","Mahnomen","Marshall","Martin","McLeod","Meeker","Mille Lacs","Morrison","Mower","Murray","Nicollet","Nobles","Norman","Olmsted","Otter Tail","Pennington","Pine","Pipestone","Polk","Pope","Ramsey","Red Lake","Redwood","Renville","Rice","Rock","Roseau","St. Louis","Scott","Sherburne","Sibley","Stearns","Steele","Stevens","Swift","Todd","Traverse","Wabasha","Wadena","Waseca","Washington","Watonwan","Wilkin","Winona","Wright","Yellow Medicine"],
  MS: ["Adams","Alcorn","Amite","Attala","Benton","Bolivar","Calhoun","Carroll","Chickasaw","Choctaw","Claiborne","Clarke","Clay","Coahoma","Copiah","Covington","DeSoto","Forrest","Franklin","George","Greene","Grenada","Hancock","Harrison","Hinds","Holmes","Humphreys","Issaquena","Itawamba","Jackson","Jasper","Jefferson","Jefferson Davis","Jones","Kemper","Lafayette","Lamar","Lauderdale","Lawrence","Leake","Lee","Leflore","Lincoln","Lowndes","Madison","Marion","Marshall","Monroe","Montgomery","Neshoba","Newton","Noxubee","Oktibbeha","Panola","Pearl River","Perry","Pike","Pontotoc","Prentiss","Quitman","Rankin","Scott","Sharkey","Simpson","Smith","Stone","Sunflower","Tallahatchie","Tate","Tippah","Tishomingo","Tunica","Union","Walthall","Warren","Washington","Wayne","Webster","Wilkinson","Winston","Yalobusha","Yazoo"],
  MO: ["Adair","Andrew","Atchison","Audrain","Barry","Barton","Bates","Benton","Bollinger","Boone","Buchanan","Butler","Caldwell","Callaway","Camden","Cape Girardeau","Carroll","Carter","Cass","Cedar","Chariton","Christian","Clark","Clay","Clinton","Cole","Cooper","Crawford","Dade","Dallas","Daviess","DeKalb","Dent","Douglas","Dunklin","Franklin","Gasconade","Gentry","Greene","Grundy","Harrison","Henry","Hickory","Holt","Howard","Howell","Iron","Jackson","Jasper","Jefferson","Johnson","Knox","Laclede","Lafayette","Lawrence","Lewis","Lincoln","Linn","Livingston","Macon","Madison","Maries","Marion","McDonald","Mercer","Miller","Mississippi","Moniteau","Monroe","Montgomery","Morgan","New Madrid","Newton","Nodaway","Oregon","Osage","Ozark","Pemiscot","Perry","Pettis","Phelps","Pike","Platte","Polk","Pulaski","Putnam","Ralls","Randolph","Ray","Reynolds","Ripley","Saline","Schuyler","Scotland","Scott","Shannon","Shelby","St. Charles","St. Clair","St. Francois","St. Louis","St. Louis City","Ste. Genevieve","Stoddard","Stone","Sullivan","Taney","Texas","Vernon","Warren","Washington","Wayne","Webster","Worth","Wright"],
  MT: ["Beaverhead","Big Horn","Blaine","Broadwater","Carbon","Carter","Cascade","Chouteau","Custer","Daniels","Dawson","Deer Lodge","Fallon","Fergus","Flathead","Gallatin","Garfield","Glacier","Golden Valley","Granite","Hill","Jefferson","Judith Basin","Lake","Lewis and Clark","Liberty","Lincoln","Madison","McCone","Meagher","Mineral","Missoula","Musselshell","Park","Petroleum","Phillips","Pondera","Powder River","Powell","Prairie","Ravalli","Richland","Roosevelt","Rosebud","Sanders","Sheridan","Silver Bow","Stillwater","Sweet Grass","Teton","Toole","Treasure","Valley","Wheatland","Wibaux","Yellowstone"],
  NE: ["Adams","Antelope","Arthur","Banner","Blaine","Boone","Box Butte","Boyd","Brown","Buffalo","Burt","Butler","Cass","Cedar","Chase","Cherry","Cheyenne","Clay","Colfax","Cuming","Custer","Dakota","Dawes","Dawson","Deuel","Dixon","Dodge","Douglas","Dundy","Fillmore","Franklin","Frontier","Furnas","Gage","Garden","Garfield","Gosper","Grant","Greeley","Hall","Hamilton","Harlan","Hayes","Hitchcock","Holt","Hooker","Howard","Jefferson","Johnson","Kearney","Keith","Keya Paha","Kimball","Knox","Lancaster","Lincoln","Logan","Loup","Madison","McPherson","Merrick","Morrill","Nance","Nemaha","Nuckolls","Otoe","Pawnee","Perkins","Phelps","Pierce","Platte","Polk","Red Willow","Richardson","Rock","Saline","Sarpy","Saunders","Scotts Bluff","Seward","Sheridan","Sherman","Sioux","Stanton","Thayer","Thomas","Thurston","Valley","Washington","Wayne","Webster","Wheeler","York"],
  NV: ["Churchill","Clark","Douglas","Elko","Esmeralda","Eureka","Humboldt","Lander","Lincoln","Lyon","Mineral","Nye","Pershing","Storey","Washoe","White Pine","Carson City"],
  NH: ["Belknap","Carroll","Cheshire","Coos","Grafton","Hillsborough","Merrimack","Rockingham","Strafford","Sullivan"],
  NJ: ["Atlantic","Bergen","Burlington","Camden","Cape May","Cumberland","Essex","Gloucester","Hudson","Hunterdon","Mercer","Middlesex","Monmouth","Morris","Ocean","Passaic","Salem","Somerset","Sussex","Union","Warren"],
  NM: ["Bernalillo","Catron","Chaves","Cibola","Colfax","Curry","De Baca","Dona Ana","Eddy","Grant","Guadalupe","Harding","Hidalgo","Lea","Lincoln","Los Alamos","Luna","McKinley","Mora","Otero","Quay","Rio Arriba","Roosevelt","San Juan","San Miguel","Sandoval","Santa Fe","Sierra","Socorro","Taos","Torrance","Union","Valencia"],
  NY: ["Albany","Allegany","Bronx","Broome","Cattaraugus","Cayuga","Chautauqua","Chemung","Chenango","Clinton","Columbia","Cortland","Delaware","Dutchess","Erie","Essex","Franklin","Fulton","Genesee","Greene","Hamilton","Herkimer","Jefferson","Kings","Lewis","Livingston","Madison","Monroe","Montgomery","Nassau","New York","Niagara","Oneida","Onondaga","Ontario","Orange","Orleans","Oswego","Otsego","Putnam","Queens","Rensselaer","Richmond","Rockland","St. Lawrence","Saratoga","Schenectady","Schoharie","Schuyler","Seneca","Steuben","Suffolk","Sullivan","Tioga","Tompkins","Ulster","Warren","Washington","Wayne","Westchester","Wyoming","Yates"],
  NC: ["Alamance","Alexander","Alleghany","Anson","Ashe","Avery","Beaufort","Bertie","Bladen","Brunswick","Buncombe","Burke","Cabarrus","Caldwell","Camden","Carteret","Caswell","Catawba","Chatham","Cherokee","Chowan","Clay","Cleveland","Columbus","Craven","Cumberland","Currituck","Dare","Davidson","Davie","Duplin","Durham","Edgecombe","Forsyth","Franklin","Gaston","Gates","Graham","Granville","Greene","Guilford","Halifax","Harnett","Haywood","Henderson","Hertford","Hoke","Hyde","Iredell","Jackson","Johnston","Jones","Lee","Lenoir","Lincoln","Macon","Madison","Martin","McDowell","Mecklenburg","Mitchell","Montgomery","Moore","Nash","New Hanover","Northampton","Onslow","Orange","Pamlico","Pasquotank","Pender","Perquimans","Person","Pitt","Polk","Randolph","Richmond","Robeson","Rockingham","Rowan","Rutherford","Sampson","Scotland","Stanly","Stokes","Surry","Swain","Transylvania","Tyrrell","Union","Vance","Wake","Warren","Washington","Watauga","Wayne","Wilkes","Wilson","Yadkin","Yancey"],
  ND: ["Adams","Barnes","Benson","Billings","Bottineau","Bowman","Burke","Burleigh","Cass","Cavalier","Dickey","Divide","Dunn","Eddy","Emmons","Foster","Golden Valley","Grand Forks","Grant","Griggs","Hettinger","Kidder","LaMoure","Logan","McHenry","McIntosh","McKenzie","McLean","Mercer","Morton","Mountrail","Nelson","Oliver","Pembina","Pierce","Ramsey","Ransom","Renville","Richland","Rolette","Sargent","Sheridan","Sioux","Slope","Stark","Steele","Stutsman","Towner","Traill","Walsh","Ward","Wells","Williams"],
  OH: ["Adams","Allen","Ashland","Ashtabula","Athens","Auglaize","Belmont","Brown","Butler","Carroll","Champaign","Clark","Clermont","Clinton","Columbiana","Coshocton","Crawford","Cuyahoga","Darke","Defiance","Delaware","Erie","Fairfield","Fayette","Franklin","Fulton","Gallia","Geauga","Greene","Guernsey","Hamilton","Hancock","Hardin","Harrison","Henry","Highland","Hocking","Holmes","Huron","Jackson","Jefferson","Knox","Lake","Lawrence","Licking","Logan","Lorain","Lucas","Madison","Mahoning","Marion","Medina","Meigs","Mercer","Miami","Monroe","Montgomery","Morgan","Morrow","Muskingum","Noble","Ottawa","Paulding","Perry","Pickaway","Pike","Portage","Preble","Putnam","Richland","Ross","Sandusky","Scioto","Seneca","Shelby","Stark","Summit","Trumbull","Tuscarawas","Union","Van Wert","Vinton","Warren","Washington","Wayne","Williams","Wood","Wyandot"],
  OK: ["Adair","Alfalfa","Atoka","Beaver","Beckham","Blaine","Bryan","Caddo","Canadian","Carter","Cherokee","Choctaw","Cimarron","Cleveland","Coal","Comanche","Cotton","Craig","Creek","Custer","Delaware","Dewey","Ellis","Garfield","Garvin","Grady","Grant","Greer","Harmon","Harper","Haskell","Hughes","Jackson","Jefferson","Johnston","Kay","Kingfisher","Kiowa","Latimer","Le Flore","Lincoln","Logan","Love","Major","Marshall","Mayes","McClain","McCurtain","McIntosh","Murray","Muskogee","Noble","Nowata","Okfuskee","Oklahoma","Okmulgee","Osage","Ottawa","Pawnee","Payne","Pittsburg","Pontotoc","Pottawatomie","Pushmataha","Roger Mills","Rogers","Seminole","Sequoyah","Stephens","Texas","Tillman","Tulsa","Wagoner","Washington","Washita","Woods","Woodward"],
  OR: ["Baker","Benton","Clackamas","Clatsop","Columbia","Coos","Crook","Curry","Deschutes","Douglas","Gilliam","Grant","Harney","Hood River","Jackson","Jefferson","Josephine","Klamath","Lake","Lane","Lincoln","Linn","Malheur","Marion","Morrow","Multnomah","Polk","Sherman","Tillamook","Umatilla","Union","Wallowa","Wasco","Washington","Wheeler","Yamhill"],
  PA: ["Adams","Allegheny","Armstrong","Beaver","Bedford","Berks","Blair","Bradford","Bucks","Butler","Cambria","Cameron","Carbon","Centre","Chester","Clarion","Clearfield","Clinton","Columbia","Crawford","Cumberland","Dauphin","Delaware","Elk","Erie","Fayette","Forest","Franklin","Fulton","Greene","Huntingdon","Indiana","Jefferson","Juniata","Lackawanna","Lancaster","Lawrence","Lebanon","Lehigh","Luzerne","Lycoming","McKean","Mercer","Mifflin","Monroe","Montgomery","Montour","Northampton","Northumberland","Perry","Philadelphia","Pike","Potter","Schuylkill","Snyder","Somerset","Sullivan","Susquehanna","Tioga","Union","Venango","Warren","Washington","Wayne","Westmoreland","Wyoming","York"],
  RI: ["Bristol","Kent","Newport","Providence","Washington"],
  SC: ["Abbeville","Aiken","Allendale","Anderson","Bamberg","Barnwell","Beaufort","Berkeley","Calhoun","Charleston","Cherokee","Chester","Chesterfield","Clarendon","Colleton","Darlington","Dillon","Dorchester","Edgefield","Fairfield","Florence","Georgetown","Greenville","Greenwood","Hampton","Horry","Jasper","Kershaw","Lancaster","Laurens","Lee","Lexington","Marion","Marlboro","McCormick","Newberry","Oconee","Orangeburg","Pickens","Richland","Saluda","Spartanburg","Sumter","Union","Williamsburg","York"],
  SD: ["Aurora","Beadle","Bennett","Bon Homme","Brookings","Brown","Brule","Buffalo","Butte","Campbell","Charles Mix","Clark","Clay","Codington","Corson","Custer","Davison","Day","Deuel","Dewey","Douglas","Edmunds","Fall River","Faulk","Grant","Gregory","Haakon","Hamlin","Hand","Hanson","Harding","Hughes","Hutchinson","Hyde","Jackson","Jerauld","Jones","Kingsbury","Lake","Lawrence","Lincoln","Lyman","Marshall","McCook","McPherson","Meade","Mellette","Miner","Minnehaha","Moody","Oglala Lakota","Pennington","Perkins","Potter","Roberts","Sanborn","Spink","Stanley","Sully","Todd","Tripp","Turner","Union","Walworth","Yankton","Ziebach"],
  TN: ["Anderson","Bedford","Benton","Bledsoe","Blount","Bradley","Campbell","Cannon","Carroll","Carter","Cheatham","Chester","Claiborne","Clay","Cocke","Coffee","Crockett","Cumberland","Davidson","Decatur","DeKalb","Dickson","Dyer","Fayette","Fentress","Franklin","Gibson","Giles","Grainger","Greene","Grundy","Hamblen","Hamilton","Hancock","Hardeman","Hardin","Hawkins","Haywood","Henderson","Henry","Hickman","Houston","Humphreys","Jackson","Jefferson","Johnson","Knox","Lake","Lauderdale","Lawrence","Lewis","Lincoln","Loudon","Macon","Madison","Marion","Marshall","Maury","McMinn","McNairy","Meigs","Monroe","Montgomery","Moore","Morgan","Obion","Overton","Perry","Pickett","Polk","Putnam","Rhea","Roane","Robertson","Rutherford","Scott","Sequatchie","Sevier","Shelby","Smith","Stewart","Sullivan","Sumner","Tipton","Trousdale","Unicoi","Union","Van Buren","Warren","Washington","Wayne","Weakley","White","Williamson","Wilson"],
  TX: ["Anderson","Andrews","Angelina","Aransas","Archer","Armstrong","Atascosa","Austin","Bailey","Bandera","Bastrop","Baylor","Bee","Bell","Bexar","Blanco","Borden","Bosque","Bowie","Brazoria","Brazos","Brewster","Briscoe","Brooks","Brown","Burleson","Burnet","Caldwell","Calhoun","Callahan","Cameron","Camp","Carson","Cass","Castro","Chambers","Cherokee","Childress","Clay","Cochran","Coke","Coleman","Collin","Collingsworth","Colorado","Comal","Comanche","Concho","Cooke","Coryell","Cottle","Crane","Crockett","Crosby","Culberson","Dallam","Dallas","Dawson","Deaf Smith","Delta","Denton","DeWitt","Dickens","Dimmit","Donley","Duval","Eastland","Ector","Edwards","Ellis","El Paso","Erath","Falls","Fannin","Fayette","Fisher","Floyd","Foard","Fort Bend","Franklin","Freestone","Frio","Gaines","Galveston","Garza","Gillespie","Glasscock","Goliad","Gonzales","Gray","Grayson","Gregg","Grimes","Guadalupe","Hale","Hall","Hamilton","Hansford","Hardeman","Hardin","Harris","Harrison","Hartley","Haskell","Hays","Hemphill","Henderson","Hidalgo","Hill","Hockley","Hood","Hopkins","Houston","Howard","Hudspeth","Hunt","Hutchinson","Irion","Jack","Jackson","Jasper","Jeff Davis","Jefferson","Jim Hogg","Jim Wells","Johnson","Jones","Karnes","Kaufman","Kendall","Kenedy","Kent","Kerr","Kimble","King","Kinney","Kleberg","Knox","Lamar","Lamb","Lampasas","La Salle","Lavaca","Lee","Leon","Liberty","Limestone","Lipscomb","Live Oak","Llano","Loving","Lubbock","Lynn","Madison","Marion","Martin","Mason","Matagorda","Maverick","McCulloch","McLennan","McMullen","Medina","Menard","Midland","Milam","Mills","Mitchell","Montague","Montgomery","Moore","Morris","Motley","Nacogdoches","Navarro","Newton","Nolan","Nueces","Ochiltree","Oldham","Orange","Palo Pinto","Panola","Parker","Parmer","Pecos","Polk","Potter","Presidio","Rains","Randall","Reagan","Real","Red River","Reeves","Refugio","Roberts","Robertson","Rockwall","Runnels","Rusk","Sabine","San Augustine","San Jacinto","San Patricio","San Saba","Schleicher","Scurry","Shackelford","Shelby","Sherman","Smith","Somervell","Starr","Stephens","Sterling","Stonewall","Sutton","Swisher","Tarrant","Taylor","Terrell","Terry","Throckmorton","Titus","Tom Green","Travis","Trinity","Tyler","Upshur","Upton","Uvalde","Val Verde","Van Zandt","Victoria","Walker","Waller","Ward","Washington","Webb","Wharton","Wheeler","Wichita","Wilbarger","Willacy","Williamson","Wilson","Winkler","Wise","Wood","Yoakum","Young","Zapata","Zavala"],
  UT: ["Beaver","Box Elder","Cache","Carbon","Daggett","Davis","Duchesne","Emery","Garfield","Grand","Iron","Juab","Kane","Millard","Morgan","Piute","Rich","Salt Lake","San Juan","Sanpete","Sevier","Summit","Tooele","Uintah","Utah","Wasatch","Washington","Wayne","Weber"],
  VT: ["Addison","Bennington","Caledonia","Chittenden","Essex","Franklin","Grand Isle","Lamoille","Orange","Orleans","Rutland","Washington","Windham","Windsor"],
  VA: ["Accomack","Albemarle","Alleghany","Amelia","Amherst","Appomattox","Arlington","Augusta","Bath","Bedford","Bland","Botetourt","Brunswick","Buchanan","Buckingham","Campbell","Caroline","Carroll","Charles City","Charlotte","Chesterfield","Clarke","Craig","Culpeper","Cumberland","Dickenson","Dinwiddie","Essex","Fairfax","Fauquier","Floyd","Fluvanna","Franklin","Frederick","Giles","Gloucester","Goochland","Grayson","Greene","Greensville","Halifax","Hanover","Henrico","Henry","Highland","Isle of Wight","James City","King and Queen","King George","King William","Lancaster","Lee","Loudoun","Louisa","Lunenburg","Madison","Mathews","Mecklenburg","Middlesex","Montgomery","Nelson","New Kent","Northampton","Northumberland","Nottoway","Orange","Page","Patrick","Pittsylvania","Powhatan","Prince Edward","Prince George","Prince William","Pulaski","Rappahannock","Richmond","Roanoke","Rockbridge","Rockingham","Russell","Scott","Shenandoah","Smyth","Southampton","Spotsylvania","Stafford","Surry","Sussex","Tazewell","Warren","Washington","Westmoreland","Wise","Wythe","York"],
  WA: ["Adams","Asotin","Benton","Chelan","Clallam","Clark","Columbia","Cowlitz","Douglas","Ferry","Franklin","Garfield","Grant","Grays Harbor","Island","Jefferson","King","Kitsap","Kittitas","Klickitat","Lewis","Lincoln","Mason","Okanogan","Pacific","Pend Oreille","Pierce","San Juan","Skagit","Skamania","Snohomish","Spokane","Stevens","Thurston","Wahkiakum","Walla Walla","Whatcom","Whitman","Yakima"],
  WV: ["Barbour","Berkeley","Boone","Braxton","Brooke","Cabell","Calhoun","Clay","Doddridge","Fayette","Gilmer","Grant","Greenbrier","Hampshire","Hancock","Hardy","Harrison","Jackson","Jefferson","Kanawha","Lewis","Lincoln","Logan","Marion","Marshall","Mason","McDowell","Mercer","Mineral","Mingo","Monongalia","Monroe","Morgan","Nicholas","Ohio","Pendleton","Pleasants","Pocahontas","Preston","Putnam","Raleigh","Randolph","Ritchie","Roane","Summers","Taylor","Tucker","Tyler","Upshur","Wayne","Webster","Wetzel","Wirt","Wood","Wyoming"],
  WI: ["Adams","Ashland","Barron","Bayfield","Brown","Buffalo","Burnett","Calumet","Chippewa","Clark","Columbia","Crawford","Dane","Dodge","Door","Douglas","Dunn","Eau Claire","Florence","Fond du Lac","Forest","Grant","Green","Green Lake","Iowa","Iron","Jackson","Jefferson","Juneau","Kenosha","Kewaunee","La Crosse","Lafayette","Langlade","Lincoln","Manitowoc","Marathon","Marinette","Marquette","Menominee","Milwaukee","Monroe","Oconto","Oneida","Outagamie","Ozaukee","Pepin","Pierce","Polk","Portage","Price","Racine","Richland","Rock","Rusk","St. Croix","Sauk","Sawyer","Shawano","Sheboygan","Taylor","Trempealeau","Vernon","Vilas","Walworth","Washburn","Washington","Waukesha","Wpaca","Waushara","Winnebago","Wood"],
  WY: ["Albany","Big Horn","Campbell","Carbon","Converse","Crook","Fremont","Goshen","Hot Springs","Johnson","Laramie","Lincoln","Natrona","Niobrara","Park","Platte","Sheridan","Sublette","Sweetwater","Teton","Uinta","Washakie","Weston"]
};

function cleanSlug(name) {
  return name.toLowerCase().replace(/[^a-z0-9]/g, '');
}

function parseCurrency(val) {
  if (!val) return 0;
  const cleaned = val.replace(/[^0-9.]/g, '');
  return parseFloat(cleaned) || 0;
}

// =========================================================================
// 3. DYNAMIC REALAUCTION COLD-FUSION ENGINE WORKER
// =========================================================================
async function scrapeRealAuctionCounty(browser, state, countyName) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800 });

  const slug = cleanSlug(countyName);
  const auctionType = REALAUCTION_STATE_TAX_TYPES[state] || 'deed';

  // Standard official RealAuction domain patterns
  const domainsToTry = [
    `https://${slug}.realtaxdeed.com`,
    `https://${slug}.realforeclose.com`,
    `https://${slug}.deedauction.net`,
    `https://${slug}.clerkauction.com`,
    `https://${slug}.${state.toLowerCase()}.realtaxdeed.com`
  ];

  let records = [];

  for (const baseUrl of domainsToTry) {
    const liveAuctionEndpoint = `${baseUrl}/index.cfm?zaction=AUCTION&zmethod=PREVIEW`;

    try {
      const response = await page.goto(liveAuctionEndpoint, { waitUntil: 'networkidle2', timeout: 10000 });
      
      // Verify valid RealAuction response
      if (response && response.status() === 200) {
        await new Promise(res => setTimeout(res, 600));

        records = await page.evaluate((st, ct, type, bUrl) => {
          const items = [];
          // Target official RealAuction ColdFusion DOM components
          const cards = document.querySelectorAll('.area_auction, div[id^="area_auction"], .AUCTION_ITEM');

          cards.forEach(card => {
            const text = card.innerText || '';

            const parcelMatch = text.match(/(?:Parcel|Parcel ID|STRAP|APN|Tax ID|PIN)[\s#:]*([A-Z0-9-]{6,30})/i);
            const parcelId = parcelMatch ? parcelMatch[1].trim() : null;

            const certMatch = text.match(/(?:Tax Deed|Certificate|Case|Item|Lien)[\s#:]*([A-Z0-9-]{4,25})/i);
            const certNum = certMatch ? certMatch[1].trim() : (parcelId ? `CERT-${parcelId}` : null);

            const openBidMatch = text.match(/(?:Opening Bid|Min Bid|Starting Bid)[\s:$]*([0-9,]+\.[0-9]{2})/i);
            const openingBid = openBidMatch ? openBidMatch[1] : '0';

            const currentBidMatch = text.match(/(?:Current Bid|High Bid|Winning Bid)[\s:$]*([0-9,]+\.[0-9]{2})/i);
            const currentBid = currentBidMatch ? currentBidMatch[1] : openingBid;

            const addrMatch = text.match(/(?:Property Address|Location|Address)[\s:]*([^\n\r]+)/i);
            let propertyAddress = addrMatch ? addrMatch[1].trim() : `${ct} County, ${st}`;

            const dateMatch = text.match(/(?:Auction Date|Sale Date|Date)[\s:]*([0-9]{1,2}\/[0-9]{1,2}\/[0-9]{4})/i);
            let auctionDate = null;
            if (dateMatch) {
              const parts = dateMatch[1].split('/');
              if (parts.length === 3) auctionDate = `${parts[2]}-${parts[0].padStart(2, '0')}-${parts[1].padStart(2, '0')}`;
            }

            const linkEl = card.querySelector('a[href*="zaction=AUCTION"]');
            const realauctionUrl = linkEl ? linkEl.href : bUrl;

            if (certNum || parcelId) {
              items.push({
                state: st,
                county: ct,
                auction_type: type,
                certificate_number: certNum || `PARCEL-${parcelId}`,
                parcel_id: parcelId,
                auction_date: auctionDate,
                opening_bid: openingBid,
                current_bid: currentBid,
                status: 'active',
                property_address: propertyAddress,
                realauction_url: realauctionUrl
              });
            }
          });

          return items;
        }, state, countyName, auctionType, baseUrl);

        if (records.length > 0) break; // Active auctions found on live site, skip fallback
      }
    } catch (err) {
      // Move to next RealAuction URL pattern
    }
  }

  await page.close();
  return { state, county: countyName, records };
}

// =========================================================================
// 4. MAIN NATIONWIDE REALAUCTION SCRAPER ENGINE
// =========================================================================
async function runNationwideRealAuctionScraper() {
  console.log("🚀 Launching 50-State Nationwide RealAuction Live Engine...");
  const startTime = Date.now();

  const browser = await puppeteer.launch({
    headless: "new",
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--window-size=1280,800']
  });

  const queue = [];
  for (const [state, counties] of Object.entries(ALL_50_STATES_COUNTIES)) {
    counties.forEach(county => queue.push({ state, county }));
  }

  console.log(`📊 Processing ${queue.length} US Counties across 50 States...`);

  let totalUpserted = 0;
  const PARALLEL_WORKERS = 5; // Process 5 parallel tabs simultaneously

  for (let i = 0; i < queue.length; i += PARALLEL_WORKERS) {
    const batch = queue.slice(i, i + PARALLEL_WORKERS);
    
    const results = await Promise.all(batch.map(item => scrapeRealAuctionCounty(browser, item.state, item.county)));

    for (const res of results) {
      if (res.records.length > 0) {
        const formatted = res.records.map(r => ({
          state: r.state,
          county: r.county,
          auction_type: r.auction_type,
          certificate_number: r.certificate_number,
          parcel_id: r.parcel_id,
          auction_date: r.auction_date || new Date().toISOString().split('T')[0],
          opening_bid: parseCurrency(r.opening_bid),
          current_bid: parseCurrency(r.current_bid),
          status: r.status,
          property_address: r.property_address,
          realauction_url: r.realauction_url,
          updated_at: new Date().toISOString()
        }));

        // Deduplicate in memory before writing to database
        const dedupedMap = new Map();
        formatted.forEach(f => dedupedMap.set(`${f.state}::${f.county}::${f.auction_type}::${f.certificate_number}`, f));
        const dedupedList = Array.from(dedupedMap.values());

        const { error } = await supabase
          .from('tax_deeds')
          .upsert(dedupedList, { onConflict: 'state,county,auction_type,certificate_number' });

        if (error) {
          console.error(`  ❌ Supabase Error [${res.state}-${res.county}]:`, error.message);
        } else {
          console.log(`  ✅ [${res.state}] ${res.county} (${res.records[0].auction_type.toUpperCase()}): Upserted ${dedupedList.length} live auction records.`);
          totalUpserted += dedupedList.length;
        }
      }
    }
  }

  await browser.close();
  const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
  console.log(`\n🎉 Nationwide 50-State Sweep Complete in ${elapsed}s! Total live RealAuction records updated: ${totalUpserted}`);
}

runNationwideRealAuctionScraper().catch(err => {
  console.error("Fatal Scraper Error:", err);
  process.exit(1);
});