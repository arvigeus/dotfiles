"""Discoverable connection details and copy controls; all network data is fake."""
import shutil
import unittest

import test_network_ports as fixtures


@unittest.skipUnless(shutil.which('qs'), 'Quickshell is required')
class ConnectionInfoTests(unittest.TestCase):
    run_qml = fixtures.NetworkFeatureQmlTests.run_qml

    def test_shared_popovers_copy_live_values_and_close_without_mutations(self):
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtTest
import Quickshell
import "drawers"
import "ui"
FloatingWindow {
 id:window;implicitWidth:480;implicitHeight:800;visible:true;color:Theme.background
 property bool bluetooth:false
 property var drawer:page.item
 QtObject {
  id:network;property bool observing:false;property bool loaded:true;property bool busy:false
  property string interfaceName:"wlan0";property string error:"";property string pending:"";property string pendingKey:""
  property string warpMode:"warp+doh";property bool warpRegisterNext:false;property var traffic:({})
  property var state:({available:true,wifiEnabled:true,hardwareEnabled:true,connectivity:"full",adapters:[{interface:"wlan0",connected:true,connection:"Home",uuid:"home",ipv4:["192.0.2.2"],details:"IPv4: 192.0.2.2/24\\nIPv4 gateway: 192.0.2.1\\nIPv4 DNS: 192.0.2.1",mac:"AA:BB:CC:DD:EE:FF"}],wired:[],networks:[],profiles:[],warp:{running:false,connected:false,mode:"",available:false},routeKey:"route-a"})
  signal completed(string operation,bool success)
  function run(){throw Error("Unexpected network mutation");}
 }
 QtObject {
  id:fakePublic;property string context:"";property string label:"Checking…";property string address:"";property int calls:0
  function lookup(){calls++;}
 }
 QtObject {id:portService;property bool observing:false;property bool available:true;property bool busy:false;property string error:"";property var ports:[];signal completed(string operation,bool success)}
 QtObject {id:speed;property bool running:false;property var result:null;property string error:"";function cancel(){}}
 QtObject {
  id:bt;property bool loaded:true;property bool busy:false;property string error:"";property string errorKey:"";property string pending:"";property string pendingKey:"";property string scanning:"";property var prompt:null
  property var state:({available:true,adapters:[{key:"/org/bluez/hci0",name:"Laptop",address:"11:22:33:44:55:66",powered:true},{key:"/org/bluez/hci1",name:"USB",address:"22:33:44:55:66:77",powered:true}],devices:[]})
  function observe(){}
  function run(){throw Error("Unexpected Bluetooth mutation");}function cancel(){pending="";}
 }
 ColumnLayout {
  anchors.fill:parent;anchors.margins:16;spacing:16
  RowLayout {
   Layout.fillWidth:true
   ShellText {text:window.bluetooth?"Bluetooth":"Wi-Fi";font.pixelSize:Theme.titleFontSize;Layout.fillWidth:true}
   Loader {sourceComponent:window.drawer?.headerActions??null}
  }
  Loader {id:page;Layout.fillWidth:true;Layout.fillHeight:true;sourceComponent:window.bluetooth?btPage:wifiPage}
 }
 Component {id:wifiPage;WifiDrawer{active:true;service:network;publicIp:fakePublic;portsService:portService;speedTest:speed}}
 Component {id:btPage;BluetoothDrawer{active:true;service:bt}}
 TestCase{id:input;when:false;parent:window.contentItem}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children||[]){const result=find(child,name);if(result)return result;}return null;}
 function check(value,message){if(!value)throw Error(message);}
 function capture(name){const directory=Quickshell.env("INFO_PREVIEW_DIR");if(directory)Qt.callLater(()=>{const requested=drawer.informationPopup.contentItem.grabToImage(result=>console.log("INFO_CAPTURE",name,result.saveToFile(directory+"/"+name+".png")));check(requested,"capture did not start");});}
 function click(item){check(item&&item.enabled,"control unavailable");input.mouseClick(item,item.width/2,item.height/2);}
 property int stage:0
 Timer{interval:180;running:true;repeat:true;onTriggered:{try{
  const info=find(window.contentItem,window.bluetooth?"bluetoothInfo":"wifiInfo");
  if(stage===0){
   check(fakePublic.calls===0,"eager public lookup");check(find(drawer,"wirelessSection").hint==="","Wireless title hides details");
   input.mouseMove(info,17,17);check(fakePublic.calls===0,"hover started lookup");click(info);
  }else if(stage===1){
   const popup=drawer.informationPopup;check(popup?.visible&&fakePublic.calls===1,"click did not open information/request lookup");
   check(popup.width<=window.width-16&&popup.height<window.height,"popover overflows window");
   const copy=find(popup.contentItem,"wifiLocalIpInfoCopy");const position=copy.mapToItem(popup.contentItem,0,0);
   check(position.x>=0&&position.x+copy.width<=popup.contentItem.width,"copy action outside popover");
   check(copy.contentItem.status===Image.Ready,"Lucide copy icon did not load");
   check(find(popup.contentItem,"wifiInterfaceInfoValue").text==="wlan0","interface missing");
   check(find(popup.contentItem,"wifiGatewayInfoValue").text==="192.0.2.1","gateway details lost");
   check(!find(popup.contentItem,"wifiPublicIpInfoCopy").enabled,"placeholder is copyable");
   click(find(popup.contentItem,"wifiLocalIpInfoCopy"));check(Quickshell.clipboardText==="192.0.2.2","local IP copy failed");
   check(popup.visible,"copy dismissed information");capture("wifi-info");fakePublic.address="203.0.113.7";fakePublic.label=fakePublic.address;
  }else if(stage===2){
   const popup=drawer.informationPopup;check(find(popup.contentItem,"wifiPublicIpInfoValue").text==="203.0.113.7","asynchronous public value stale");
   click(find(popup.contentItem,"wifiPublicIpInfoCopy"));check(Quickshell.clipboardText==="203.0.113.7","public IP copy failed");
   input.keyClick(Qt.Key_Escape);check(!drawer.informationPopup&&drawer.active,"Escape dismissed drawer or retained popover");
   check(info.activeFocus,"dismissal did not restore focus");click(info);
  }else if(stage===3){
   const context=fakePublic.context;const calls=fakePublic.calls;
   network.state=Object.assign({},network.state,{adapters:[Object.assign({},network.state.adapters[0],{traffic:{received:123}})]});
   check(fakePublic.context===context&&fakePublic.calls===calls,"traffic invalidated public lookup");
   network.state=Object.assign({},network.state,{routeKey:"route-b"});
  }else if(stage===4){
   check(fakePublic.calls===3,"route change did not refresh open information");
   drawer.active=false;check(!drawer.informationPopup,"dismissal left information open");window.bluetooth=true;
  }else if(stage===5){click(info);capture("bluetooth-info");}
  else if(stage===6){
   const popup=drawer.informationPopup;check(popup?.visible,"Bluetooth information missing");
   check(find(popup.contentItem,"bluetoothAdapterInfoValue").text==="Laptop","adapter missing");
   click(find(popup.contentItem,"bluetoothInterfaceInfoCopy"));check(Quickshell.clipboardText==="hci0","Bluetooth interface copy failed");
   click(find(popup.contentItem,"bluetoothAddressInfoCopy"));check(Quickshell.clipboardText==="11:22:33:44:55:66","Bluetooth address copy failed");
   drawer.adapterKey="/org/bluez/hci1";check(!drawer.informationPopup,"adapter change left information open");window.implicitWidth=320;
  }else if(stage===7){click(info);capture("bluetooth-info-narrow");}
  else if(stage===8){
   const popup=drawer.informationPopup;check(popup.width<=window.width-16,"narrow information width");
   check(find(popup.contentItem,"bluetoothAdapterInfoValue").text==="USB","stale adapter details");
   click(info);check(!drawer.informationPopup,"second click failed to toggle");click(info);
  }else if(stage===9){
   input.mouseClick(window.contentItem,5,window.height-5);check(!drawer.informationPopup,"outside click failed");
   console.log("FEATURE_PASS");Qt.quit();return;
  }
  stage++;
 }catch(e){console.error("FEATURE_FAIL",stage,e.message);Qt.quit();}}}
}
''')
