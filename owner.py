"""Owner workspace; financial controls are separately authorized by ops.actor."""
from flask import Blueprint
from core import login_required
import admin
bp=Blueprint('owner',__name__,url_prefix='/owner')
@bp.route('/',methods=['GET','POST'])
@login_required('owner')
def dashboard():return admin.dashboard.__wrapped__()
@bp.get('/live')
@login_required('owner')
def live():return admin.live.__wrapped__()
@bp.get('/reservations')
@login_required('owner')
def reservations():return admin.reservations.__wrapped__()
