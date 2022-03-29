import csv
import time
from selenium import webdriver
from bs4 import BeautifulSoup

firstname=''                        #Add your LastNAme
lastname=''                         #Add your FirstName
joblink=[]                          #Initialized list to store links
maxcount=50                         #Max daily apply quota for Naukri
keywords=['','']                     #Add you list of role you want to apply
location = ''                        #Add your location for within India no
applied =0
failed = 0
applied_list={
    'passed':[],
    'failed':[]
}

profile = webdriver.FirefoxProfile("") #Add your Root directory path
driver = webdriver.Firefox(profile)

time.sleep(10)
for k in keywords:
    for i in range(2):
        url = "https://www.naukri.com/"+k.lower.replace(' ','-')+"-jobs-in-"+location.lower.replace(' ','-')+"-"+str(i+1)
        driver.get(url)
        print(url)
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source,'html5lib')
        results = soup.find(class_='list')
        job_elems = results.find_all('article',class_='jobTuple bgWhite br4 mb-8')
        for job_elem in job_elems:
            joblink.append(job_elem.find('a',class_='title fw500 ellipsis').get('href'))


for i in joblink:
    time.sleep(3)
    driver.get(i)   
    if applied <=maxcount:
        try:
            time.sleep(3)
            driver.find_element_by_xpath("//*[text()='Apply']").click()
            time.sleep(2)
            applied +=1
            applied_list['passed'].append(i)
            print('Applied for ',i, " Count", applied)

        except Exception as e: 
            failed+=1
            applied_list['failed'].append(i)
            print(e, "Failed " ,failed)
        try:    
            if driver.find_element_by_xpath("//*[text()='Your daily quota has been expired.']"):
                print('MAX Limit reached closing browser')
                driver.close()
                break
            if driver.find_element_by_xpath("//*[text()=' 1. First Name']"):
                driver.find_element_by_xpath("//input[@id='CUSTOM-FIRSTNAME']").send_keys(firstname)
            if driver.find_element_by_xpath("//*[text()=' 2. Last Name']"):
                driver.find_element_by_xpath("//input[@id='CUSTOM-LASTNAME']").send_keys(lastname);
            if driver.find_element_by_xpath("//*[text()='Submit and Apply']"):
                driver.find_element_by_xpath("//*[text()='Submit and Apply']").click()
            
                
        except:
            pass
            
    else:
        driver.close()
        break
print('Completed applying closing browser saving in applied jobs csv')
try:driver.close()
except:pass
csv_file = "naukriapplied.csv"
try:
    with open(csv_file, 'a') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=['passed', 'failed'])
        writer.writeheader()
        for data in applied_list:
            writer.writerow(data)
except IOError:
    print("I/O error")