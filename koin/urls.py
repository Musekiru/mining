from django.urls import path
from . import views

urlpatterns = [
    path('base/', views.base, name='base'),
    path('landing/', views.landing, name='landing'),
    path('login/', views.login, name='login'),
    path('register/', views.register, name='register'),
    path("logout/", views.logout_view, name="logout"),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('mine', views.mine, name='mine'),
    path('mine/start/', views.start_mining, name='start_mining'),
    path('mine/stop/', views.stop_mining, name='stop_mining'),
    path('mine/status/', views.miner_status, name='miner_status'),
    path('boosts/', views.boosts, name='boosts'),
    path('boosts/buy/', views.buy_boost, name='buy_boost'),
    path('boosts/confirm/<int:purchase_id>/', views.confirm_payment, name='confirm_payment'),
    path('donate/', views.donate, name='donate'),
    path('donate/confirm/<int:donation_id>/', views.confirm_donation, name='confirm_donation'),
]
