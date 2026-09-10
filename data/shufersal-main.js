//$(document).ready(function () {
//    $(".ddlClass").change(function () {
//        var strSelected = "";
//        $(".ddlClass option:selected").each(function () {
//            strSelected += $(this)[0].value;
//        });
//        var url = "/FileObject/UpdateCategory/" + strSelected;

//        $.post(url, function (data) {
//            var json = jQuery.parseJSON(data);
//            $(function () {
//                var content = '';
//                //content += '<tbody>'; -- **superfluous**

//                for (var i = 0; i < json.length; i++) {
//                    content += '<tr >';
//                    content += '<td> ' + json[i].Name + '</td>';
//                    content += '<td>' + json[i].Category + '</td>';
//                    content += '<td>' + json[i].Type + '</td>';
//                    content += '<td>' + json[i].Size + '</td>';
//                    content += '<td>' + json[i].Time + '</td>';
//                    content += '<td><a href="' + json[i].URL + '" target="_blank" class="edit">Download</a> </td>';
//                    content += '</tr>';
//                }
//                // content += '</tbody>';-- **superfluous**
//                //$('table tbody').replaceWith(content);  **incorrect..**
//                $('#filesTable tbody').html(content);  // **better. give the table a ID, and replace**
//            });
//        });
//    });
//});

var spinner = null;

var opts = {
    lines: 13, // The number of lines to draw
    length: 20, // The length of each line
    width: 10, // The line thickness
    radius: 30, // The radius of the inner circle
    corners: 1, // Corner roundness (0..1)
    rotate: 0, // The rotation offset
    direction: 1, // 1: clockwise, -1: counterclockwise
    color: '#000', // #rgb or #rrggbb or array of colors
    speed: 1, // Rounds per second
    trail: 60, // Afterglow percentage
    shadow: false, // Whether to render a shadow
    hwaccel: false, // Whether to use hardware acceleration
    className: 'spinner', // The CSS class to assign to the spinner
    zIndex: 2e9, // The z-index (defaults to 2000000000)
    top: '50%', // Top position relative to parent
    left: '50%' // Left position relative to parent
};

$('#ddlCategory').change(function (e) {
    e.preventDefault();
    var url = serverUrl + 'FileObject/UpdateCategory';
    StartSpin();
    $.get(url, { catID: $(this).val(), storeId: $('#ddlStore') .val()}, function (result) {
        $('#gridContent').html(result);
        StopSpin();
    });
});

$('#ddlStore').change(function (e) {
    e.preventDefault();
    var url = serverUrl + 'FileObject/UpdateCategory';
    StartSpin();
    $.get(url, { catID: $('#ddlCategory').val(), storeId: $(this).val() }, function (result) {
        $('#gridContent').html(result);
        StopSpin();
    });
});

function StartSpin() {
  //  if (spinner == null) {
        var target = document.getElementById('gridContent');
        spinner = new Spinner(opts).spin(target);
   // }
   // else {
   //     spinner.spin();
  //  }
}


function StopSpin() {
    if (spinner != null) {
        spinner.stop()
    }
    
}


$(document).ajaxStart(function () {
    StartSpin();
}).ajaxStop(function () {
    StopSpin();
});

